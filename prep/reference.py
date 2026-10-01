"""Independent reference results for reconciling the Power BI model.

Reads orders.csv and the generation manifest only. Uses integer cents, so no
float rounding is involved. Nothing here imports the evidence step or reads
Power BI, so a mistake in either cannot leak into the reference.

Usage: uv run python prep/reference.py [--data-dir DIR]
"""

from __future__ import annotations

import argparse
import calendar
import csv
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from paths import data_dir_from_args

ALL = "ALL"


def to_cents(text: str) -> int:
    d = Decimal(text)
    if d < 0 or d.as_tuple().exponent < -2:
        raise ValueError(f"not a nonnegative two-decimal amount: {text!r}")
    return int(d * 100)


def load_orders(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return [
            {
                "order_id": r["order_id"],
                "date": date.fromisoformat(r["order_date"]),
                "region": r["region"],
                "category": r["category"] or None,
                "cents": to_cents(r["revenue_amount"]),
            }
            for r in csv.DictReader(f)
        ]


def month_key(d: date) -> int:
    return d.year * 100 + d.month


def prev_month_key(mk: int) -> int:
    y, m = divmod(mk, 100)
    return (y - 1) * 100 + 12 if m == 1 else y * 100 + m - 1


def month_length(mk: int) -> int:
    return calendar.monthrange(mk // 100, mk % 100)[1]


def comparison_window(mk: int, cutoff: date) -> tuple[int, str]:
    """Last comparable day of month mk, and the coverage status of mk."""
    if mk == month_key(cutoff) and cutoff.day < month_length(mk):
        return cutoff.day, "partial"
    return month_length(mk), "complete"


def pct(num: int, den: int) -> str | None:
    """Exact ratio rendered to 6 decimals; None when the denominator is zero."""
    if den == 0:
        return None
    return str((Decimal(num) / Decimal(den)).quantize(Decimal("0.000001")))


def build(orders: list[dict], manifest: dict) -> dict:
    cutoff = date.fromisoformat(manifest["snapshot_cutoff"])
    cov_start = date.fromisoformat(manifest["intended_coverage"]["start"])
    regions = [r["region"] for r in manifest["regions"]]

    # Aggregate by (month, region, day) with categories kept separate.
    cell: dict[tuple, dict] = defaultdict(lambda: {"orders": 0, "cents": 0})
    for o in orders:
        k = (month_key(o["date"]), o["region"], o["date"].day, o["category"] or "UNKNOWN")
        cell[k]["orders"] += 1
        cell[k]["cents"] += o["cents"]

    def total(mk: int, region: str, max_day: int = 31, category: str | None = None) -> dict:
        out = {"orders": 0, "cents": 0}
        for (m, r, d, c), v in cell.items():
            if m == mk and (region == ALL or r == region) and d <= max_day and (
                category is None or c == category
            ):
                out["orders"] += v["orders"]
                out["cents"] += v["cents"]
        return out

    months = sorted({month_key(o["date"]) for o in orders})
    first_month = month_key(cov_start)
    categories = [c["category"] for c in manifest["categories"]] + ["UNKNOWN"]

    slices = []
    for mk in months:
        end_day, status = comparison_window(mk, cutoff)
        pmk = prev_month_key(mk)
        has_prior = mk > first_month
        # Complete months compare full months; only a partial month aligns days.
        prior_end = month_length(pmk) if status == "complete" else min(end_day, month_length(pmk))
        for region in [ALL, *regions]:
            cur = total(mk, region)
            unknown = total(mk, region, category="UNKNOWN")
            comp_cur = total(mk, region, end_day)
            prior = total(pmk, region, prior_end) if has_prior else None
            change = comp_cur["cents"] - prior["cents"] if prior else None
            slices.append({
                "month_key": mk,
                "region": region,
                "coverage_status": status,
                "comparison_end_day": end_day,
                "orders": cur["orders"],
                "revenue_cents": cur["cents"],
                "unknown_category_orders": unknown["orders"],
                "unknown_category_revenue_cents": unknown["cents"],
                "category_revenue_cents": {
                    c: total(mk, region, category=c)["cents"] for c in categories
                },
                "category_completeness": pct(cur["orders"] - unknown["orders"], cur["orders"]),
                "comparable_revenue_cents": comp_cur["cents"],
                "prior_month_key": pmk if has_prior else None,
                "prior_window": f"{pmk}: days 1-{prior_end}" if has_prior else None,
                "prior_revenue_cents": prior["cents"] if prior else None,
                "revenue_change_cents": change,
                "revenue_change_pct": pct(change, prior["cents"]) if prior else None,
            })

    # What a naive full-month comparison would claim for the partial month.
    pm = month_key(cutoff)
    naive = {
        "month_key": pm,
        "note": "Full observed September (1-20) against the full 31 days of August. "
        "Shown only to quantify the mistake the comparison policy avoids.",
        "current_cents": total(pm, ALL)["cents"],
        "prior_cents": total(prev_month_key(pm), ALL)["cents"],
    }
    naive["change_pct"] = pct(naive["current_cents"] - naive["prior_cents"], naive["prior_cents"])

    return {
        "snapshot_id": manifest["snapshot_id"],
        "orders_sha256": manifest["orders_sha256"],
        "totals": {
            "orders": len(orders),
            "revenue_cents": sum(o["cents"] for o in orders),
            "unknown_category_orders": sum(o["category"] is None for o in orders),
            "unknown_category_revenue_cents": sum(o["cents"] for o in orders if o["category"] is None),
            "min_order_date": min(o["date"] for o in orders).isoformat(),
            "max_order_date": max(o["date"] for o in orders).isoformat(),
            "distinct_order_ids": len({o["order_id"] for o in orders}),
        },
        "slices": slices,
        "naive_partial_month_comparison": naive,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    out = data_dir_from_args(parser)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    ref = build(load_orders(out / manifest["orders_file"]), manifest)
    (out / "reference_results.json").write_text(json.dumps(ref, indent=2) + "\n", encoding="utf-8")

    print(f"{ref['totals']['orders']} orders, revenue {Decimal(ref['totals']['revenue_cents']) / 100}")
    print(f"{'month':>6} {'region':>8} {'cover':>8} {'revenue':>12} {'prior':>12} {'chg%':>8} {'catcompl':>8}")
    for s in ref["slices"]:
        chg = s["revenue_change_pct"]
        print(f"{s['month_key']:>6} {s['region']:>8} {s['coverage_status']:>8} "
              f"{Decimal(s['revenue_cents']) / 100:>12} "
              f"{'-' if s['prior_revenue_cents'] is None else Decimal(s['prior_revenue_cents']) / 100:>12} "
              f"{'-' if chg is None else f'{Decimal(chg) * 100:.1f}':>8} "
              f"{Decimal(s['category_completeness']) * 100:>7.1f}%")
    n = ref["naive_partial_month_comparison"]
    print(f"naive Sep(1-20) vs full Aug: {Decimal(n['change_pct']) * 100:.1f}% (not used)")


if __name__ == "__main__":
    main()
