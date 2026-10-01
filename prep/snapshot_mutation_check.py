"""Prove the report notices when the loaded orders differ from the profiled snapshot.

For each mutation (one changed amount, date, category label or region, or one
missing row) this script rewrites data/orders.csv, refreshes only the Orders
table in the open Desktop model, and reads the 'Snapshot Consistency' measure.
It expects "Mismatch" for every mutation and a match for the untouched file,
which it always restores, even on error.

Not read-only: it changes data/orders.csv while running and refreshes Orders.

Usage: uv run python prep/snapshot_mutation_check.py [--port N] [--data-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import sys

from paths import REPO_ROOT, data_dir_from_args
from reconcile_live import Model, find_port

ROW = 1235  # an arbitrary order line (line 0 is the header)


def mutate(lines: list[str], kind: str) -> list[str]:
    out = list(lines)
    order_id, order_date, region, category, amount = out[ROW].split(",")
    if kind == "amount":
        amount = "1.00" if amount != "1.00" else "2.00"
    elif kind == "date":
        order_date = "2026-04-02" if order_date != "2026-04-02" else "2026-04-03"
    elif kind == "category label":
        category = "Software" if category != "Software" else "Hardware"
    elif kind == "region":
        region = "South" if region != "South" else "North"
    elif kind == "missing row":
        del out[ROW]
        return out
    out[ROW] = ",".join([order_id, order_date, region, category, amount])
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int)
    data = data_dir_from_args(parser)
    port = parser.parse_args().port or find_port()
    model = Model(port)
    db = model.query("SELECT [CATALOG_NAME] FROM $SYSTEM.DBSCHEMA_CATALOGS")[0]["CATALOG_NAME"]

    def refresh_and_read() -> str:
        cmd = model.conn.CreateCommand()
        cmd.CommandText = '{"refresh": {"type": "full", "objects": [{"database": "%s", "table": "Orders"}]}}' % db
        cmd.ExecuteNonQuery()
        return model.query('EVALUATE ROW ( "s", [Snapshot Consistency] )')[0]["s"]

    path = data / "orders.csv"
    original = path.read_bytes()
    lines = original.decode("utf-8").split("\n")
    results = []
    try:
        for kind in ("amount", "date", "category label", "region", "missing row"):
            path.write_bytes("\n".join(mutate(lines, kind)).encode("utf-8"))
            message = refresh_and_read()
            results.append({"mutation": kind, "message": message, "ok": message.startswith("Mismatch")})
    finally:
        path.write_bytes(original)
        message = refresh_and_read()
        results.append({"mutation": "none (restored)", "message": message,
                        "ok": message.startswith("Loaded orders match")})

    out = REPO_ROOT / "verification" / "snapshot_mutations.json"
    out.write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for r in results:
        print(f"{'ok  ' if r['ok'] else 'FAIL'} {r['mutation']:16} -> {r['message']}")
    sys.exit(0 if all(r["ok"] for r in results) else 1)


if __name__ == "__main__":
    main()
