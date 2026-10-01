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
