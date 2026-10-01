"""Reconcile the open Power BI Desktop model against the Python reference.

Connects to the local Analysis Services instance that Desktop starts for the
open MetricEvidence project (found by looking for the 'Evidence Column Stats'
table), evaluates DAX through the ADOMD.NET client that ships with Desktop, and
compares every value with reference_results.json and the evidence CSVs.

Read-only: it only runs DAX queries. Refresh the model in Desktop first.

Usage: uv run python prep/reconcile_live.py [--port N] [--data-dir DIR]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from paths import REPO_ROOT, data_dir_from_args

DESKTOP_BIN = Path(os.environ.get("PBI_DESKTOP_BIN", r"C:\Program Files\Microsoft Power BI Desktop\bin"))
WORKSPACES = Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Power BI Desktop" / "AnalysisServicesWorkspaces"
REGIONS = ("North", "Central", "South")
UNAVAILABLE = "Evidence unavailable for this selection"


def _adomd():
    import clr  # pythonnet

    sys.path.append(str(DESKTOP_BIN))
    clr.AddReference("Microsoft.PowerBI.AdomdClient")
    from Microsoft.AnalysisServices.AdomdClient import AdomdConnection  # type: ignore

    return AdomdConnection


def _plain(value):
    """.NET value to a culture-independent Python value.

    pythonnet already unboxes bool, integers, double and string. Decimal and
    DateTime are formatted with the invariant culture: their default ToString
    follows the machine locale (it-IT writes 5571609,31).
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    from System.Globalization import CultureInfo  # type: ignore

    name = value.GetType().FullName
    if name == "System.DBNull":
        return None
    if name == "System.Decimal":
        return Decimal(value.ToString(CultureInfo.InvariantCulture))
    if name == "System.DateTime":
        return value.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture)
    return str(value)


class Model:
    def __init__(self, port: int):
        self.conn = _adomd()(f"Data Source=localhost:{port}")
        self.conn.Open()

    def query(self, dax: str) -> list[dict]:
        cmd = self.conn.CreateCommand()
        cmd.CommandText = dax
        reader = cmd.ExecuteReader()
        names = [reader.GetName(i) for i in range(reader.FieldCount)]
        rows = []
        while reader.Read():
            rows.append({n.split("[")[-1].rstrip("]"): _plain(reader.GetValue(i)) for i, n in enumerate(names)})
        reader.Close()
        return rows

    def tables(self) -> set[str]:
        return {r["Name"] for r in self.query("SELECT [Name] FROM $SYSTEM.TMSCHEMA_TABLES")}


def find_port() -> int:
    for ws in sorted(WORKSPACES.glob("AnalysisServicesWorkspace_*"), key=lambda p: p.stat().st_mtime, reverse=True):
        port_file = ws / "Data" / "msmdsrv.port.txt"
        if not port_file.exists():
            continue
        port = int(port_file.read_bytes().decode("utf-16-le").strip())
        try:
            if "Evidence Column Stats" in Model(port).tables():
                return port
        except Exception:  # a stale workspace whose Desktop has closed
            continue
    raise SystemExit("No open Desktop model with 'Evidence Column Stats' found. Open the PBIP first.")


@dataclass
class Results:
    checks: list[dict] = field(default_factory=list)

    def check(self, group: str, name: str, expected, actual, tol: Decimal = Decimal(0)) -> None:
        if isinstance(expected, Decimal) and isinstance(actual, Decimal):
            ok = abs(expected - actual) <= tol
        else:
            ok = expected == actual
        self.checks.append({"group": group, "check": name, "expected": str(expected),
                            "actual": str(actual), "ok": ok})

    @property
    def failed(self) -> list[dict]:
        return [c for c in self.checks if not c["ok"]]


def cents(c: int | None) -> Decimal | None:
    return None if c is None else Decimal(c) / 100


def ratio(s: str | None) -> Decimal | None:
    return None if s is None else Decimal(s)


PCT_TOL = Decimal("0.0000005")  # reference ratios are rounded to 6 decimals

MEASURES = """
    "rev", [Revenue], "orders", [Order Count], "comp", [Revenue (Comparable)],
    "prior", [Revenue (Prior Comparable)], "chg", [Revenue Change], "chgpct", [Revenue Change %],
    "compl", [Category Completeness], "unknown", [Unknown Category Revenue],
    "evcompl", [Evidence Category Completeness], "evnulls", [Evidence Category Nulls],
    "evrows", [Evidence Rows Profiled], "evcheck", [Evidence Category Check],
    "scope", [Evidence Scope Label], "note", [Comparison Note]
"""


def slice_query(month: int, region: str | None, category_filter: str | None = None) -> str:
    filters = [f"TREATAS ( {{ {month} }}, 'Date'[month_key] )"]
    if region:
        filters.append(f'TREATAS ( {{ "{region}" }}, Region[region_key] )')
    if category_filter:
        filters.append(f'TREATAS ( {{ "{category_filter}" }}, Category[category_key] )')
    return f"EVALUATE CALCULATETABLE ( ROW ( {MEASURES} ), {', '.join(filters)} )"


def run(model: Model, data: Path) -> Results:
    ref = json.loads((data / "reference_results.json").read_text(encoding="utf-8"))
    with (data / "evidence_checks.csv").open(newline="", encoding="utf-8") as f:
        cat_checks = {r["scope_id"]: r["check_status"] for r in csv.DictReader(f)
                      if r["check_code"] == "max_null_percentage" and r["column_name"] == "category"}
    res = Results()

    # 1. Whole snapshot.
    t = model.query("""EVALUATE ROW ( "rev", [Revenue], "orders", [Order Count],
        "unknown", [Unknown Category Revenue], "snap", [Snapshot Consistency],
        "bycat", SUMX ( VALUES ( Category[category_key] ), [Revenue] ) )""")[0]
    res.check("totals", "revenue", cents(ref["totals"]["revenue_cents"]), t["rev"])
    res.check("totals", "orders", ref["totals"]["orders"], t["orders"])
    res.check("unknown retained", "Unknown category revenue",
              cents(ref["totals"]["unknown_category_revenue_cents"]), t["unknown"])
    res.check("unknown retained", "sum over categories incl. Unknown = total", t["rev"], t["bycat"])
    res.check("snapshot", "Snapshot Consistency", True, str(t["snap"]).startswith("Same snapshot"))

    # 2-5. Every month x (all regions | one region).
    slices = {(s["month_key"], s["region"]): s for s in ref["slices"]}
    for (month, region), s in sorted(slices.items()):
        g = f"{month} {region}"
        v = model.query(slice_query(month, None if region == "ALL" else region))[0]
        res.check(g, "revenue", cents(s["revenue_cents"]), v["rev"])
        res.check(g, "orders", s["orders"], v["orders"])
        res.check(g, "comparable revenue", cents(s["comparable_revenue_cents"]), v["comp"])
        res.check(g, "prior comparable revenue", cents(s["prior_revenue_cents"]), v["prior"])
        res.check(g, "revenue change", cents(s["revenue_change_cents"]), v["chg"])
        res.check(g, "revenue change %", ratio(s["revenue_change_pct"]), v["chgpct"], PCT_TOL)
        res.check(g, "category completeness (model)", ratio(s["category_completeness"]), v["compl"], PCT_TOL)
        res.check(g, "unknown category revenue", cents(s["unknown_category_revenue_cents"]),
                  v["unknown"] or Decimal(0))
        res.check(g, "dataprof nulls = independent count", s["unknown_category_orders"], v["evnulls"])
        res.check(g, "dataprof rows = independent count", s["orders"], v["evrows"])
        res.check(g, "category completeness (dataprof)", ratio(s["category_completeness"]), v["evcompl"], PCT_TOL)
        scope_id = str(month) if region == "ALL" else f"{month}-{region}"
        res.check(g, "check status matches evidence_checks.csv",
                  cat_checks[scope_id].replace("_", " ").capitalize(), v["evcheck"])
        res.check(g, "scope label names the region",
                  True, (" · All regions · " if region == "ALL" else f" · {region} · ") in str(v["scope"]))

        # Category interactions must not change the evidence or completeness.
        h = model.query(slice_query(month, None if region == "ALL" else region, "Hardware"))[0]
        for key in ("compl", "evcompl", "evnulls", "evrows", "evcheck", "scope"):
            res.check(g, f"category filter leaves {key} unchanged", v[key], h[key])
        u = model.query(slice_query(month, None if region == "ALL" else region, "UNKNOWN"))[0]
        res.check(g, "Unknown category filter leaves completeness unchanged", v["compl"], u["compl"])

    # 3. Region contributions sum to the total change.
    for month in sorted({m for m, _ in slices}):
        total = slices[(month, "ALL")]["revenue_change_cents"]
        if total is None:
            continue
        rows = model.query(f"""EVALUATE CALCULATETABLE (
            ADDCOLUMNS ( VALUES ( Region[region_key] ), "chg", [Revenue Change] ),
            TREATAS ( {{ {month} }}, 'Date'[month_key] ) )""")
        res.check(f"{month} contributions", "sum of region changes = total change",
                  cents(total), sum(r["chg"] for r in rows))

    # 3b. The bridge: two totals, region steps in between, all adding up.
    for month in sorted({m for m, _ in slices}):
        cur = slices[(month, "ALL")]
        if cur["prior_month_key"] is None:
            continue
        rows = model.query(f"""EVALUATE CALCULATETABLE (
            SUMMARIZECOLUMNS ( 'Month Coverage'[month_key], "bridge", [Bridge Revenue] ),
            TREATAS ( {{ {month} }}, 'Date'[month_key] ) )""")
        got = {r["month_key"]: r["bridge"] for r in rows}
        res.check(f"{month} bridge", "only the two compared months appear",
                  sorted([cur["prior_month_key"], month]), sorted(got))
        res.check(f"{month} bridge", "start = prior comparable", cents(cur["prior_revenue_cents"]),
                  got.get(cur["prior_month_key"]))
        res.check(f"{month} bridge", "end = comparable", cents(cur["comparable_revenue_cents"]), got.get(month))

    # Headlines state the change and contributions, never a cause or a data-quality claim.
    for region in (None, "North"):
        h = model.query(f"""EVALUATE CALCULATETABLE ( ROW ( "h1", [Headline What Changed], "h2", [Headline Contribution] ),
            TREATAS ( {{ 202609 }}, 'Date'[month_key] ){'' if region is None else f', TREATAS ( {{ "{region}" }}, Region[region_key] )'} )""")[0]
        text = f"{h['h1']} {h['h2']}".lower()
        res.check("headline", f"{region or 'all regions'}: names the window", True, "sep 1–20 vs aug 1–20" in text)
        res.check("headline", f"{region or 'all regions'}: no causal or quality wording", True,
                  not any(w in text for w in ("because", "due to", "caused", "missing", "quality", "label")))
        res.check("headline", f"{region or 'all regions'}: never prints (Blank)", True,
                  h["h2"] is not None)

    # 4. September uses the aligned window.
    sep = model.query(slice_query(202609, None))[0]
    res.check("comparison policy", "September note", "Sep 1–20 vs Aug 1–20", sep["note"])
    apr = model.query(slice_query(202604, None))[0]
    res.check("comparison policy", "April has no prior (blank, not zero)", None, apr["prior"])
    res.check("comparison policy", "April change % blank", None, apr["chgpct"])
    res.check("comparison policy", "April note", "No comparable prior period in this snapshot", apr["note"])

    # 7. Unsupported scopes show unavailable, not a plausible global value.
    two = model.query(f"""EVALUATE CALCULATETABLE ( ROW ( {MEASURES} ),
        TREATAS ( {{ 202609 }}, 'Date'[month_key] ), TREATAS ( {{ "North", "South" }}, Region[region_key] ) )""")[0]
    res.check("unsupported scope", "two regions: rows profiled blank", None, two["evrows"])
    res.check("unsupported scope", "two regions: completeness blank", None, two["evcompl"])
    res.check("unsupported scope", "two regions: label says unavailable", True, str(two["scope"]).startswith(UNAVAILABLE))
    allm = model.query(f"EVALUATE ROW ( {MEASURES} )")[0]
    res.check("unsupported scope", "no single month: completeness blank", None, allm["evcompl"])
    res.check("unsupported scope", "no single month: label says unavailable", True, str(allm["scope"]).startswith(UNAVAILABLE))
    res.check("unsupported scope", "no single month: change blank", None, allm["chg"])

    # Evidence history rows (page 2) take their month from the row, not the slicer.
    hist = model.query("""EVALUATE CALCULATETABLE (
        SUMMARIZECOLUMNS ( 'Month Coverage'[month_label], 'Month Coverage'[month_key],
            "evcompl", [Evidence Category Completeness], "rev", [Revenue by Month] ),
        TREATAS ( { 202609 }, 'Date'[month_key] ), TREATAS ( { "North" }, Region[region_key] ) )""")
    for h in hist:
        s = slices[(h["month_key"], "North")]
        res.check("history rows", f"{h['month_key']} North dataprof completeness",
                  ratio(s["category_completeness"]), h["evcompl"], PCT_TOL)
        res.check("history rows", f"{h['month_key']} North revenue ignores month slicer",
                  cents(s["revenue_cents"]), h["rev"])
    return res


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int)
    data = data_dir_from_args(parser)
    port = parser.parse_args().port or find_port()
    res = run(Model(port), data)
    out = REPO_ROOT / "verification" / "live_reconciliation.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"port": port, "checks": res.checks}, indent=1, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    for c in res.failed:
        print(f"FAIL [{c['group']}] {c['check']}: expected {c['expected']}, got {c['actual']}")
    print(f"{len(res.checks) - len(res.failed)}/{len(res.checks)} checks passed (port {port}) -> {out}")
    sys.exit(1 if res.failed else 0)


if __name__ == "__main__":
    main()
