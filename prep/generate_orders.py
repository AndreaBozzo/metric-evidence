"""Generate the deterministic synthetic orders snapshot and its manifest.

The manifest is demo ground truth: what the generator intended and did. It is
not something dataprof inferred, and the evidence step reads coverage from it
rather than guessing completeness from the order dates.

Usage: uv run python prep/generate_orders.py [--data-dir DIR]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

from paths import data_dir_from_args

SEED = 20260401
GENERATOR_VERSION = "1.0.0"

COVERAGE_START = date(2026, 4, 1)
COVERAGE_END = date(2026, 9, 30)  # intended coverage: the whole of September
SNAPSHOT_CUTOFF = date(2026, 9, 20)  # the extract stops here (inclusive)
SNAPSHOT_ID = "snap-2026-09-20"

# Base orders per day across all regions, before weekday and growth factors.
BASE_DAILY_ORDERS = 111.0
WEEKDAY_FACTOR = (1.08, 1.08, 1.08, 1.08, 1.08, 0.80, 0.80)  # Mon..Sun, mean 1.0
MONTHLY_GROWTH = 0.015  # +1.5% order rate per month after April

REGIONS = (("North", 0.40), ("Central", 0.35), ("South", 0.25))
# (category, mix share, median order value, lognormal sigma)
CATEGORIES = (
    ("Hardware", 0.28, 320.0, 0.55),
    ("Software", 0.27, 140.0, 0.55),
    ("Services", 0.20, 520.0, 0.55),
    ("Accessories", 0.25, 38.0, 0.55),
)
BASE_MISSING_CATEGORY = 0.02

# Controlled scenarios. Each is applied by the code below exactly as described.
SCENARIOS = [
    {
        "id": "S1_volume_decline",
        "kind": "genuine_business_change",
        "region": "North",
        "start": "2026-09-01",
        "end": "2026-09-30",
        "parameter": {"order_rate_multiplier": 0.80},
        "description": "North receives 20% fewer orders per day in September. "
        "Order values are unchanged. This is a real change in the business, "
        "not a data defect.",
    },
    {
        "id": "S2_missing_category",
        "kind": "data_quality_degradation",
        "region": "North",
        "start": "2026-09-01",
        "end": "2026-09-30",
        "parameter": {
            "missing_category_probability": 0.11,
            "baseline_missing_category_probability": BASE_MISSING_CATEGORY,
        },
        "description": "In North during September the category label is missing "
        "for 11% of orders (baseline 2% everywhere). Missingness is random and "
        "independent of the true category; revenue is unaffected.",
    },
    {
        "id": "S3_partial_snapshot",
        "kind": "coverage_limitation",
        "region": None,
        "start": "2026-09-21",
        "end": "2026-09-30",
        "parameter": {"snapshot_cutoff": SNAPSHOT_CUTOFF.isoformat()},
        "description": "Orders were generated for the whole of September, but the "
        "snapshot contains only orders dated up to and including 20 September. "
        "Later orders exist in the simulated business but not in this extract.",
    },
]

# Explicit names: strftime("%b") follows the process locale.
MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

ORDER_FIELDS = ("order_id", "order_date", "region", "category", "revenue_amount")


def _poisson(rng: random.Random, lam: float) -> int:
    """Knuth's method; fine for the per-region daily rates used here (< 60)."""
    limit = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _normal(rng: random.Random) -> float:
    """Box-Muller from rng.random() only, so output is stable across Python versions."""
    u1 = 1.0 - rng.random()  # (0, 1]
    u2 = rng.random()
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


def _pick(rng: random.Random, weighted: list[tuple[str, float]]) -> str:
    x = rng.random() * sum(w for _, w in weighted)
    for name, weight in weighted:
        x -= weight
        if x < 0:
            return name
    return weighted[-1][0]


def _months_between(start: date, d: date) -> int:
    return (d.year - start.year) * 12 + d.month - start.month


def _in_scenario(s: dict, region: str, d: date) -> bool:
    if s["region"] is not None and s["region"] != region:
        return False
    return date.fromisoformat(s["start"]) <= d <= date.fromisoformat(s["end"])


def generate() -> tuple[list[dict], dict]:
    rng = random.Random(SEED)
    s1, s2 = SCENARIOS[0], SCENARIOS[1]
    cat_mix = [(name, share) for name, share, _, _ in CATEGORIES]
    cat_price = {name: (median, sigma) for name, _, median, sigma in CATEGORIES}

    generated: list[dict] = []
    d = COVERAGE_START
    while d <= COVERAGE_END:
        day_rate = (
            BASE_DAILY_ORDERS
            * WEEKDAY_FACTOR[d.weekday()]
            * (1.0 + MONTHLY_GROWTH * _months_between(COVERAGE_START, d))
        )
        for region, share in REGIONS:
            lam = day_rate * share
            if _in_scenario(s1, region, d):
                lam *= s1["parameter"]["order_rate_multiplier"]
            p_missing = (
                s2["parameter"]["missing_category_probability"]
                if _in_scenario(s2, region, d)
                else BASE_MISSING_CATEGORY
            )
            for _ in range(_poisson(rng, lam)):
                category = _pick(rng, cat_mix)
                median, sigma = cat_price[category]
                cents = max(1, round(median * math.exp(sigma * _normal(rng)) * 100))
                label = None if rng.random() < p_missing else category
                generated.append(
                    {"order_date": d, "region": region, "true_category": category,
                     "category": label, "revenue_cents": cents}
                )
        d += timedelta(days=1)

    for i, row in enumerate(generated, start=1):
        row["order_id"] = f"ORD-{i:06d}"

    snapshot = [r for r in generated if r["order_date"] <= SNAPSHOT_CUTOFF]
    withheld = [r for r in generated if r["order_date"] > SNAPSHOT_CUTOFF]
    s2_rows = [r for r in snapshot if _in_scenario(s2, r["region"], r["order_date"])]

    manifest = {
        "purpose": "Demo ground truth written by the generator. Not inferred by dataprof.",
        "generator_version": GENERATOR_VERSION,
        "seed": SEED,
        "snapshot_id": SNAPSHOT_ID,
        "grain": "one row per order",
        "intended_coverage": {"start": COVERAGE_START.isoformat(), "end": COVERAGE_END.isoformat()},
        "snapshot_cutoff": SNAPSHOT_CUTOFF.isoformat(),
        "snapshot_cutoff_meaning": "orders dated on or before this date are in the extract",
        "comparison_policy": {
            "complete_month": "full month vs full previous month",
            "partial_month": "days 1..N of the month vs days 1..N of the previous month, "
            "where N is the last observed day; N is capped at the previous month's length",
            "first_month": "no comparable prior period in the snapshot",
            "note": "A simple demo policy. It is not seasonally adjusted.",
        },
        "regions": [{"region": r, "base_share": s} for r, s in REGIONS],
        "categories": [
            {"category": n, "mix_share": s, "median_order_value": m, "lognormal_sigma": sg}
            for n, s, m, sg in CATEGORIES
        ],
        "baseline_missing_category_probability": BASE_MISSING_CATEGORY,
        "scenarios": SCENARIOS,
        "counts": {
            "rows_generated_including_withheld": len(generated),
            "rows_in_snapshot": len(snapshot),
            "rows_withheld_after_cutoff": len(withheld),
            "s2_rows_in_snapshot": len(s2_rows),
            "s2_rows_missing_category": sum(r["category"] is None for r in s2_rows),
        },
    }
    return snapshot, manifest


def _money(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def write_orders(rows: list[dict], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(ORDER_FIELDS)
        for r in rows:
            w.writerow([r["order_id"], r["order_date"].isoformat(), r["region"],
                        r["category"] or "", _money(r["revenue_cents"])])


def write_dimensions(out: Path) -> None:
    with (out / "dim_region.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["region_key", "region_name", "sort_order"])
        for i, (r, _) in enumerate(REGIONS, start=1):
            w.writerow([r, r, i])

    with (out / "dim_category.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["category_key", "category_name", "sort_order", "is_unknown"])
        for i, (c, _, _, _) in enumerate(CATEGORIES, start=1):
            w.writerow([c, c, i, "false"])
        w.writerow(["UNKNOWN", "Unknown (label missing)", len(CATEGORIES) + 1, "true"])

    # The date dimension spans the intended coverage, so days after the snapshot
    # cutoff exist as dates with no orders rather than silently disappearing.
    with (out / "dim_date.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["date", "month_key", "month_start", "month_label", "month_short",
                    "day_of_month", "in_snapshot"])
        d = COVERAGE_START
        while d <= COVERAGE_END:
            w.writerow([d.isoformat(), d.year * 100 + d.month, d.replace(day=1).isoformat(),
                        f"{MONTH_ABBR[d.month - 1]} {d.year}", MONTH_ABBR[d.month - 1], d.day,
                        "true" if d <= SNAPSHOT_CUTOFF else "false"])
            d += timedelta(days=1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    out = data_dir_from_args(parser)
    rows, manifest = generate()
    orders_path = out / "orders.csv"
    write_orders(rows, orders_path)
    write_dimensions(out)
    manifest["orders_file"] = "orders.csv"
    manifest["orders_sha256"] = hashlib.sha256(orders_path.read_bytes()).hexdigest()
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    c = manifest["counts"]
    print(f"orders.csv: {c['rows_in_snapshot']} rows in snapshot "
          f"({c['rows_withheld_after_cutoff']} generated after the cutoff were withheld)")
    print(f"sha256 {manifest['orders_sha256']}")


if __name__ == "__main__":
    main()
