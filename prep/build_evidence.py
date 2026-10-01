"""Profile the orders snapshot with dataprof and export flat evidence tables.

Three kinds of evidence are kept apart, each tagged with evidence_source:

* evidence_column_stats.csv  dataprof column statistics, one row per
                             (scope, column). Grain: scope_id x column_name.
* evidence_checks.csv        dataprof check() outcomes, one row per
                             (scope, check). Grain: scope_id x check_code x column.
* month_coverage.csv         coverage from the generation manifest plus a Python
                             check of the data against it. Grain: month_key.

Scopes are the whole snapshot, each observed month, and each observed
month x region. Whole-month and month x region rows overlap by construction;
consumers must pick one scope_kind, never add them together.

Native dataprof outputs are written to dataprof_native/ for inspection.

Usage: uv run python prep/build_evidence.py [--data-dir DIR]
"""

from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import json
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import dataprof as dp

from paths import data_dir_from_args

# Demo policy evaluated by dataprof's check(). Thresholds are percentages.
NULL_ALLOWANCE = {"order_id": 0.0, "order_date": 0.0, "region": 0.0, "category": 5.0,
                  "revenue_amount": 0.0}
MAX_DUPLICATE_ROWS = 0
IDENTIFIER_COLUMNS = ["order_id"]
CHECK_SCOPE = "full_source"  # inconclusive, never pass, if evidence were sampled

MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

STATS_FIELDS = [
    "snapshot_id", "scope_id", "scope_kind", "month_key", "region_key", "column_name",
    "dataprof_data_type", "observed_rows", "null_count", "null_percentage", "unique_count",
    "unique_count_is_approximate", "min_value", "max_value", "mean_value",
    "key_uniqueness_pct", "sampling_applied", "source_exhausted", "evidence_source",
]
CHECK_FIELDS = [
    "snapshot_id", "scope_id", "scope_kind", "month_key", "region_key", "check_code",
    "column_name", "dimension", "comparison", "threshold", "observed_value", "check_status",
    "gate_verdict", "evidence_coverage", "not_evaluated_reason", "message", "evidence_source",
]
COVERAGE_FIELDS = [
    "snapshot_id", "month_key", "month_label", "trend_label", "expected_start", "expected_end",
    "expected_days", "observed_through", "covered_days", "coverage_status",
    "comparison_end_day", "prior_month_key", "comparison_label", "orders_in_snapshot",
    "orders_after_cutoff", "cutoff_check", "evidence_source",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _month_key(iso_date: str) -> int:
    return int(iso_date[:4]) * 100 + int(iso_date[5:7])


def _blank(v: object) -> object:
    """Null stays an empty cell; booleans use the lowercase form Power Query parses."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return v


def load_columns(path: Path) -> tuple[list[str], list[list[str | None]]]:
    """Rows as strings, empty cells as None, exactly as a CSV reader sees them."""
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = [[v if v != "" else None for v in row] for row in reader]
    return header, rows


def scopes(header: list[str], rows: list[list[str | None]]) -> list[dict]:
    """Month and month x region slices of the snapshot, as column dicts."""
    i_date, i_region = header.index("order_date"), header.index("region")
    groups: dict[tuple, list] = defaultdict(list)
    for row in rows:
        mk = _month_key(row[i_date])
        groups[(mk, None)].append(row)
        groups[(mk, row[i_region])].append(row)
    out = []
    for (mk, region), members in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
        out.append({
            "scope_id": f"{mk}" if region is None else f"{mk}-{region}",
            "scope_kind": "month" if region is None else "month_region",
            "month_key": mk,
            "region_key": region,
            "columns": {name: [r[j] for r in members] for j, name in enumerate(header)},
        })
    return out


def stats_rows(report: dp.ProfileReport, scope: dict, snapshot_id: str, source: str) -> list[dict]:
    uniq = (report.quality.uniqueness or {}) if report.quality is not None else {}
    out = []
    for col in report.profiles:
        is_key = uniq.get("key_column") == col.name
        out.append({
            "snapshot_id": snapshot_id,
            "scope_id": scope["scope_id"],
            "scope_kind": scope["scope_kind"],
            "month_key": scope["month_key"],
            "region_key": scope["region_key"],
            "column_name": col.name,
            "dataprof_data_type": col.data_type,
            "observed_rows": col.total_count,
            "null_count": col.null_count,
            "null_percentage": col.null_percentage,
            "unique_count": col.unique_count,
            "unique_count_is_approximate": col.unique_count_is_approximate,
            "min_value": col.min,
            "max_value": col.max,
            "mean_value": col.mean,
            "key_uniqueness_pct": uniq.get("key_uniqueness") if is_key else None,
            "sampling_applied": report.sampling_applied,
            "source_exhausted": report.source_exhausted,
            "evidence_source": source,
        })
    return out


def check_rows(gate: dp.QualityGateResult, scope: dict, snapshot_id: str, source: str) -> list[dict]:
    out = []
    for c in gate.checks:
        out.append({
            "snapshot_id": snapshot_id,
            "scope_id": scope["scope_id"],
            "scope_kind": scope["scope_kind"],
            "month_key": scope["month_key"],
            "region_key": scope["region_key"],
            "check_code": c.code,
            "column_name": c.column,
            "dimension": c.dimension,
            "comparison": c.expected.get("comparison"),
            "threshold": c.expected.get("value"),
            "observed_value": c.observed,
            "check_status": c.status,  # passed | failed | not_evaluated
            "gate_verdict": gate.verdict,  # pass | fail | inconclusive
            "evidence_coverage": c.evidence.get("coverage"),
            "not_evaluated_reason": (c.reason or {}).get("reason"),
            "message": c.message,
            "evidence_source": source,
        })
    return out


def coverage_rows(manifest: dict, header: list[str], rows: list[list[str | None]]) -> list[dict]:
    """Coverage comes from the manifest; the data is only checked against it."""
    cutoff = date.fromisoformat(manifest["snapshot_cutoff"])
    start = date.fromisoformat(manifest["intended_coverage"]["start"])
    end = date.fromisoformat(manifest["intended_coverage"]["end"])
    i_date = header.index("order_date")
    per_month: dict[int, int] = defaultdict(int)
    after_cutoff: dict[int, int] = defaultdict(int)
    for row in rows:
        mk = _month_key(row[i_date])
        per_month[mk] += 1
        if date.fromisoformat(row[i_date]) > cutoff:
            after_cutoff[mk] += 1

    out = []
    m = start.replace(day=1)
    first = True
    while m <= end:
        mk = m.year * 100 + m.month
        last = m.replace(day=calendar.monthrange(m.year, m.month)[1])
        exp_start, exp_end = max(m, start), min(last, end)
        observed_through = min(exp_end, cutoff) if exp_start <= cutoff else None
        covered = (observed_through - exp_start).days + 1 if observed_through else 0
        expected = (exp_end - exp_start).days + 1
        status = ("complete" if covered == expected else
                  "partial" if covered > 0 else "not_in_snapshot")
        prev = (m - timedelta(days=1)).replace(day=1)
        name, prev_name = MONTH_ABBR[m.month - 1], MONTH_ABBR[prev.month - 1]
        if first:
            label = "No prior month in this snapshot"
        elif status == "partial":
            label = f"{name} 1–{covered} vs {prev_name} 1–{covered}"
        else:
            label = f"{name} vs {prev_name}, full months"
        out.append({
            "snapshot_id": manifest["snapshot_id"],
            "month_key": mk,
            "month_label": f"{name} {m.year}",
            "trend_label": f"{name} (1–{covered})" if status == "partial" else name,
            "expected_start": exp_start.isoformat(),
            "expected_end": exp_end.isoformat(),
            "expected_days": expected,
            "observed_through": observed_through.isoformat() if observed_through else None,
            "covered_days": covered,
            "coverage_status": status,
            "comparison_end_day": covered if status == "partial" else expected,
            "prior_month_key": None if first else prev.year * 100 + prev.month,
            "comparison_label": label,
            "orders_in_snapshot": per_month.get(mk, 0),
            "orders_after_cutoff": after_cutoff.get(mk, 0),
            "cutoff_check": "pass" if after_cutoff.get(mk, 0) == 0 else "fail",
            "evidence_source": "generation manifest + Python check",
        })
        first = False
        m = last + timedelta(days=1)
    return out


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: _blank(r[k]) for k in fields})


FINGERPRINT_EPOCH = date(2026, 1, 1)


def fingerprint(data: Path, header: list[str], rows: list[list[str | None]]) -> dict:
    """Content fingerprint the report recomputes from the orders it loaded.

    Each checksum weights a column by the order number (ORD-000123 -> 123), so
    changing any single value, or adding or removing a row, changes at least one
    of them. They are not cryptographic: they detect accidental divergence, not
    deliberate tampering. Codes come from the dimension files Power BI loads.
    """
    def codes(name: str, key: str) -> dict[str, int]:
        with (data / name).open(newline="", encoding="utf-8") as f:
            return {r[key]: int(r["sort_order"]) for r in csv.DictReader(f)}

    region_code = codes("dim_region.csv", "region_key")
    category_code = codes("dim_category.csv", "category_key")
    col = {name: header.index(name) for name in header}
    out = {"revenue_cents_total": 0, "checksum_revenue": 0, "checksum_date": 0,
           "checksum_category": 0, "checksum_region": 0}
    for r in rows:
        n = int(r[col["order_id"]][4:])
        cents = int(Decimal(r[col["revenue_amount"]]) * 100)
        out["revenue_cents_total"] += cents
        out["checksum_revenue"] += n * cents
        out["checksum_date"] += n * (date.fromisoformat(r[col["order_date"]]) - FINGERPRINT_EPOCH).days
        out["checksum_category"] += n * category_code[r[col["category"]] or "UNKNOWN"]
        out["checksum_region"] += n * region_code[r[col["region"]]]
    return out


def build(data: Path) -> dict:
    manifest = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
    orders_path = data / manifest["orders_file"]
    sha = _sha256(orders_path)
    if sha != manifest["orders_sha256"]:
        raise SystemExit("orders.csv does not match the manifest; regenerate before profiling")
    snapshot_id = manifest["snapshot_id"]
    native = data / "dataprof_native"
    native.mkdir(exist_ok=True)
    stats_src = f"dataprof {dp.__version__} column_profiles"
    check_src = f"dataprof {dp.__version__} check()"

    header, rows = load_columns(orders_path)

    # The whole snapshot is profiled from the file itself, the slices in memory.
    dataset_scope = {"scope_id": "dataset", "scope_kind": "dataset", "month_key": None,
                     "region_key": None}
    reports = [(dataset_scope, dp.profile_file(
        orders_path, sampling=dp.SamplingStrategy.none(), identifier_columns=IDENTIFIER_COLUMNS))]
    for scope in scopes(header, rows):
        # In-memory sources are always read in full; dataprof ignores sampling for them.
        reports.append((scope, dp.profile(scope.pop("columns"), name=scope["scope_id"],
                                          identifier_columns=IDENTIFIER_COLUMNS)))

    stats, checks = [], []
    for scope, report in reports:
        if report.sampling_applied or not report.source_exhausted:
            raise SystemExit(f"{scope['scope_id']}: expected a complete scan")
        gate = report.check(max_null_percentage=NULL_ALLOWANCE,
                            max_duplicate_rows=MAX_DUPLICATE_ROWS, scope=CHECK_SCOPE)
        (native / f"{scope['scope_id']}.profile.json").write_text(report.to_json(), encoding="utf-8")
        (native / f"{scope['scope_id']}.check.json").write_text(gate.to_json(), encoding="utf-8")
        stats += stats_rows(report, scope, snapshot_id, stats_src)
        checks += check_rows(gate, scope, snapshot_id, check_src)

    coverage = coverage_rows(manifest, header, rows)
    write_csv(data / "evidence_column_stats.csv", STATS_FIELDS, stats)
    write_csv(data / "evidence_checks.csv", CHECK_FIELDS, checks)
    write_csv(data / "month_coverage.csv", COVERAGE_FIELDS, coverage)
    snapshot = {
        "snapshot_id": snapshot_id,
        "snapshot_cutoff": manifest["snapshot_cutoff"],
        "intended_coverage_start": manifest["intended_coverage"]["start"],
        "intended_coverage_end": manifest["intended_coverage"]["end"],
        "orders_rows": len(rows),
        "orders_sha256": sha,
        "generator_seed": manifest["seed"],
        "dataprof_version": dp.__version__,
        **fingerprint(data, header, rows),
    }
    write_csv(data / "snapshot.csv", list(snapshot), [snapshot])
    return {"stats": stats, "checks": checks, "coverage": coverage, "snapshot": snapshot}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    result = build(data_dir_from_args(parser))
    print(f"{len(result['stats'])} column-stat rows, {len(result['checks'])} check rows, "
          f"{len(result['coverage'])} coverage rows")
    for r in result["checks"]:
        if r["check_status"] != "passed":
            print(f"  {r['scope_id']:>14} {r['check_code']} {r['column_name']}: "
                  f"{r['check_status']} (observed {r['observed_value']}, allowed {r['threshold']})")


if __name__ == "__main__":
    main()
