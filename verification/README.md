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
| An unevaluated dataprof check stays `not_evaluated` / `inconclusive`, written as null | `pytest` | pass |
| Evidence refuses an `orders.csv` that does not match its manifest | `pytest` | pass |
| Revenue, orders, comparable and prior revenue, change, change %, category completeness: DAX = Python reference, all 24 month × (all, North, Central, South) slices | `reconcile_live.py` | pass |
| Category filters (Hardware, Unknown) leave evidence and completeness unchanged | `reconcile_live.py` | pass |
| Unsupported scopes (two regions; no single month) show "Evidence unavailable for this selection" and blank values | `reconcile_live.py` | pass |
| Evidence history rows take their month from the row, not from the month slicer | `reconcile_live.py` | pass |
| Bridge shows only the two compared months; start = prior window, end = current window | `reconcile_live.py` | pass |
| Headlines name the window and contain no causal or data-quality wording | `reconcile_live.py` | pass |
| Evidence and orders describe the same snapshot (id and row count) | `reconcile_live.py`, MCP DAX query | pass |
| All PBIR/PBIP JSON files valid against Microsoft's published schemas | `validate_pbip.py` | 39 files, 0 errors |
| All 60 measures parse (no measure in error state) | `$SYSTEM.TMSCHEMA_MEASURES` | pass |
| All 60 measures have a description; numeric measures have a format string | MCP `measure_operations List`, `INFO.MEASURES()` | pass |
| Relationships: 3, all many-to-one, single direction, fact to dimension | MCP `relationship_operations List` | pass |

Totals: **10/10 tests**, **533/533 live reconciliation checks**
(`live_reconciliation.json` holds every expected and actual value).

The reconciliation was checked for sensitivity: corrupting one prior-revenue
cent and one null count in the reference made exactly those two checks fail.
Two of the tests were checked the same way by reintroducing the bugs they
guard against.

## Observed in Desktop (screenshots in `docs/img/`)

* The PBIP opens, refreshes (about 5 s) and both pages render with the theme.
* Month slicer defaults to Sep; region slicer selection switches the evidence
  panel to that region (North: completeness 89.8%, check failed).
* The drillthrough page shows North with the month carried over and synced.
* Clicking a month bar in the trend does not change the KPI or evidence
  (interactions set to No filter; measures are also independent of it).

## Not verified automatically

* Right-click → Drill through was not clicked by the agent. The page binding,
  the drillthrough filter and "keep all filters" are set in the PBIR files, and
  the page was rendered with a North drill filter and the synced month, but the
  click path itself is a manual check.
* Visual layout at other Desktop zoom levels or display scaling.
