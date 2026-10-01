"""Focused tests: determinism, comparison boundaries, adapter honesty, reconciliation."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import date
from pathlib import Path

import dataprof as dp
import pytest

import build_evidence
import generate_orders
import reference

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """A fresh snapshot, evidence and reference built in a temp folder."""
    out = tmp_path_factory.mktemp("data")
    rows, manifest = generate_orders.generate()
    generate_orders.write_orders(rows, out / "orders.csv")
    generate_orders.write_dimensions(out)
    manifest["orders_file"] = "orders.csv"
    manifest["orders_sha256"] = hashlib.sha256((out / "orders.csv").read_bytes()).hexdigest()
    (out / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    evidence = build_evidence.build(out)
    ref = reference.build(reference.load_orders(out / "orders.csv"), manifest)
    return {"dir": out, "manifest": manifest, "evidence": evidence, "ref": ref}


def _slice(ref, mk, region):
    return next(s for s in ref["slices"] if s["month_key"] == mk and s["region"] == region)


# --- determinism -----------------------------------------------------------------

def test_generation_is_deterministic_and_matches_checked_in_manifest(built):
    checked_in = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    assert built["manifest"]["orders_sha256"] == checked_in["orders_sha256"]
    assert built["manifest"]["counts"] == checked_in["counts"]


# --- comparison boundaries -------------------------------------------------------

def test_partial_month_window_and_boundaries():
    cutoff = date(2026, 9, 20)
    assert reference.comparison_window(202609, cutoff) == (20, "partial")
    assert reference.comparison_window(202608, cutoff) == (31, "complete")
    # A cutoff on the month's last day makes a complete month, not a partial one.
    assert reference.comparison_window(202609, date(2026, 9, 30)) == (30, "complete")
    assert reference.prev_month_key(202601) == 202512


def test_comparison_policy_on_built_snapshot(built):
    ref = built["ref"]
    assert _slice(ref, 202609, "ALL")["prior_window"] == "202608: days 1-20"
    # Complete months compare against the full previous month, not an aligned window.
    assert _slice(ref, 202606, "ALL")["prior_revenue_cents"] == _slice(ref, 202605, "ALL")["revenue_cents"]
    assert _slice(ref, 202606, "ALL")["prior_window"] == "202605: days 1-31"
    # The first month has no comparable prior period: absent, not zero.
    apr = _slice(ref, 202604, "ALL")
    assert apr["prior_revenue_cents"] is None and apr["revenue_change_pct"] is None
    assert reference.pct(5, 0) is None


# --- reconciliation --------------------------------------------------------------

def test_unknown_category_revenue_is_retained(built):
    ref = built["ref"]
    for s in ref["slices"]:
        assert sum(s["category_revenue_cents"].values()) == s["revenue_cents"]
    assert ref["totals"]["unknown_category_revenue_cents"] > 0


def test_region_contributions_sum_to_total_change(built):
    ref = built["ref"]
    for mk in (202605, 202606, 202607, 202608, 202609):
        parts = [_slice(ref, mk, r)["revenue_change_cents"] for r in ("North", "Central", "South")]
        assert sum(parts) == _slice(ref, mk, "ALL")["revenue_change_cents"]


def test_dataprof_null_counts_match_independent_counts(built):
    ref, stats = built["ref"], built["evidence"]["stats"]
    cat = {(r["scope_kind"], r["month_key"], r["region_key"]): r for r in stats
           if r["column_name"] == "category"}
    for s in ref["slices"]:
        key = ("month", s["month_key"], None) if s["region"] == "ALL" else (
            "month_region", s["month_key"], s["region"])
        assert cat[key]["null_count"] == s["unknown_category_orders"]
        assert cat[key]["observed_rows"] == s["orders"]
    assert cat[("dataset", None, None)]["null_count"] == ref["totals"]["unknown_category_orders"]


def test_month_scope_equals_sum_of_its_disjoint_region_scopes(built):
    """Region slices partition a month, so their counts add up. The month row is
    the same evidence again: adding both scope kinds together would double count."""
    stats = [r for r in built["evidence"]["stats"] if r["column_name"] == "category"]
    for month in {r["month_key"] for r in stats if r["scope_kind"] == "month"}:
        whole = next(r for r in stats if r["scope_kind"] == "month" and r["month_key"] == month)
        parts = [r for r in stats if r["scope_kind"] == "month_region" and r["month_key"] == month]
        assert len(parts) == 3
        assert sum(p["null_count"] for p in parts) == whole["null_count"]
        assert sum(p["observed_rows"] for p in parts) == whole["observed_rows"]


def test_scenarios_are_visible_in_evidence_and_reference(built):
    ev, ref = built["evidence"], built["ref"]
    failed = [(c["scope_id"], c["column_name"]) for c in ev["checks"] if c["check_status"] != "passed"]
    assert failed == [("202609-North", "category")]
    assert _slice(ref, 202609, "North")["revenue_change_cents"] < 0
    cov = {c["month_key"]: c for c in ev["coverage"]}
    assert cov[202609]["coverage_status"] == "partial"
    assert cov[202609]["observed_through"] == "2026-09-20"
    assert all(c["coverage_status"] == "complete" for k, c in cov.items() if k != 202609)


# --- adapter honesty -------------------------------------------------------------

def test_unevaluated_checks_stay_unevaluated(tmp_path):
    report = dp.profile({"a": ["1", None], "b": ["x", "y"]})
    gate = report.check(max_null_percentage={"not_a_column": 0.0})
    scope = {"scope_id": "t", "scope_kind": "month", "month_key": 1, "region_key": None}
    rows = build_evidence.check_rows(gate, scope, "snap", "test")
    assert rows[0]["check_status"] == "not_evaluated"
    assert rows[0]["gate_verdict"] == "inconclusive"
    assert rows[0]["observed_value"] is None
    build_evidence.write_csv(tmp_path / "c.csv", build_evidence.CHECK_FIELDS, rows)
    with (tmp_path / "c.csv").open(newline="", encoding="utf-8") as f:
        written = next(csv.DictReader(f))
    assert written["observed_value"] == ""  # null, not zero
    assert written["not_evaluated_reason"] == "column_not_profiled"


def test_evidence_refuses_a_snapshot_that_does_not_match_its_manifest(built, tmp_path):
    for name in ("orders.csv", "manifest.json"):
        (tmp_path / name).write_bytes((built["dir"] / name).read_bytes())
    with (tmp_path / "orders.csv").open("a", encoding="utf-8") as f:
        f.write("ORD-999999,2026-09-20,North,Hardware,1.00\n")
    with pytest.raises(SystemExit):
        build_evidence.build(tmp_path)


def test_snapshot_fingerprint_changes_with_any_single_value(built):
    """The report compares these sums with the orders it loaded, so a changed amount,
    date, label or region, or a missing row, must move at least one of them."""
    header, rows = build_evidence.load_columns(built["dir"] / "orders.csv")
    base = build_evidence.fingerprint(built["dir"], header, rows)
    assert base["revenue_cents_total"] == built["ref"]["totals"]["revenue_cents"]
    i = {name: header.index(name) for name in header}
    mutations = {
        "amount": lambda r: r.__setitem__(i["revenue_amount"], "1.00"),
        "date": lambda r: r.__setitem__(i["order_date"], "2026-04-02"),
        "label": lambda r: r.__setitem__(i["category"], "Software" if r[i["category"]] != "Software" else "Hardware"),
        "region": lambda r: r.__setitem__(i["region"], "South" if r[i["region"]] != "South" else "North"),
    }
    for name, mutate in mutations.items():
        changed = [list(r) for r in rows]
        mutate(changed[1234])
        assert build_evidence.fingerprint(built["dir"], header, changed) != base, name
    assert build_evidence.fingerprint(built["dir"], header, rows[:-1]) != base, "missing row"


def test_configure_report_rewrites_only_the_data_folder(tmp_path):
    import configure_report

    # Work on a copy normalised to the placeholder, so the test does not depend on
    # whether this clone has already been configured.
    copy = tmp_path / "expressions.tmdl"
    copy.write_text(configure_report.EXPRESSIONS.read_text(encoding="utf-8"), encoding="utf-8")
    configure_report.set_data_folder(configure_report.PLACEHOLDER, copy)
    shipped = copy.read_text(encoding="utf-8")

    target = r"D:\clones\metric-evidence\data" + "\\"
    old, new = configure_report.set_data_folder(target, copy)
    assert (old, new) == (configure_report.PLACEHOLDER, target)
    changed = copy.read_text(encoding="utf-8")
    assert f'expression DataFolder = "{target}" meta' in changed
    assert [line for line in changed.splitlines() if "DataFolder =" not in line] == \
        [line for line in shipped.splitlines() if "DataFolder =" not in line]
    configure_report.set_data_folder(configure_report.PLACEHOLDER, copy)
    assert copy.read_text(encoding="utf-8") == shipped
