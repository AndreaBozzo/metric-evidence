# Verification record

Run on 2026-10-01, Windows 11, Power BI Desktop 2.158.1177.0 (September 2026),
Python 3.12.10, dataprof 0.12.0, Power BI Authoring MCP `@microsoft/powerbi-modeling-mcp`
1.0.0 (win32-x64 binary 1.0.0).

## Automated

| Check | How | Result |
|---|---|---|
| Generator is deterministic; the snapshot matches its manifest | `pytest` | pass |
| Partial-month window (Sep 1–20 vs Aug 1–20); complete months against full months; first month has no prior (blank, not zero) | `pytest`, `reconcile_live.py` | pass |
| Unknown category revenue retained: category revenue incl. Unknown = total, in every slice | `pytest`, `reconcile_live.py` | pass |
| Region contributions add up to the total change, every month | `pytest`, `reconcile_live.py` | pass |
| dataprof null and row counts equal independent counts, every month and month × region | `pytest`, `reconcile_live.py` | pass |
| Month scope = sum of its disjoint region scopes (never added together in the model) | `pytest` | pass |
| An unevaluated dataprof check stays `not_evaluated` / `inconclusive`, written as null | `pytest`; end-to-end by injecting one into the model | pass |
| Evidence refuses an `orders.csv` that does not match its manifest | `pytest` | pass |
| Snapshot fingerprint changes when any single amount, date, label or region changes, or a row is missing | `pytest` | pass |
| Revenue, orders, comparable and prior revenue, change, change %, category completeness: DAX = Python reference, all 24 month × (all, North, Central, South) slices | `reconcile_live.py` | pass |
| Category filters (every category, incl. Unknown) leave evidence and completeness unchanged | `reconcile_live.py` | pass |
| Unsupported scopes (two regions; two months; no single month) show "Evidence unavailable for this selection" and blank values | `reconcile_live.py` | pass |
| Evidence history rows take their month from the row, not from the month slicer | `reconcile_live.py` | pass |
| Bridge shows only the two compared months; start = prior window, end = current window | `reconcile_live.py` | pass |
| Headlines name the window and contain no causal or data-quality wording | `reconcile_live.py` | pass |
| Loaded orders match the profiled snapshot: ids, row count, revenue total and four per-column checksums | `reconcile_live.py`, MCP DAX query | pass |
| One changed amount, date, category label or region, or one missing row, makes the report say "Mismatch"; restoring the file makes it match again | `snapshot_mutation_check.py` (`snapshot_mutations.json`) | 6/6 |
| All PBIR/PBIP JSON files valid against Microsoft's published schemas | `validate_pbip.py` | 40 files, 0 errors |
| All 61 measures parse and have a description | `$SYSTEM.TMSCHEMA_MEASURES`, MCP `measure_operations List` | pass |
| Relationships: 3, all many-to-one, single direction, fact to dimension | MCP `relationship_operations List` | pass |

Totals: **11/11 tests**, **533/533 live reconciliation checks**
(`live_reconciliation.json` holds every expected and actual value),
**6/6 snapshot mutation checks**.

Sensitivity: corrupting one prior-revenue cent and one null count in the
reference made exactly those two reconciliation checks fail (531/533); two
tests were checked the same way by reintroducing the bugs they guard against.

## Navigation, exercised in Desktop

Clicked through the real UI (screenshots in `drillthrough/`):

1. Right-click North in **Change by region, %** → Drill through → Segment detail:
   the page shows North (revenue −25.5%, orders −21.7%, check failed).
2. On the detail page, select Aug: North +9.6% / +4.9% (Aug vs Jul, full
   months), evidence switches to Aug (complete, passed).
3. Back (Ctrl+click in Desktop): page 1 keeps Aug through the synced slicer
   (all regions +5.3%).
4. Central and South drill through the same way: +3.1% and +5.1%, each with its
   own evidence scope.

Two defects this found, both fixed: waterfall breakdown steps offer no
drillthrough (the hint now sits on the ranked % bars, which do), and "keep all
filters" pinned the detail page's month slicer to a single month (the
drillthrough now carries only the region; the month syncs through the slicer).
The detail page no longer stores a preset region, so opened directly it shows
all regions.

## Not covered

* Visual layout at other Desktop zoom levels or display scaling.
* Power BI Service rendering (the project is local by design).
