# Enhancement notes

Observations collected while building Metric Evidence. Each is something
noticed in practice, not a wish list.

## dataprof (0.12.0)

1. **Sampling warning names the wrong source type.** Passing `sampling=` with a
   plain `dict` of columns warns "Config kwargs ['sampling'] are ignored for
   DataFrame/Arrow sources". The source was neither. Naming the actual input
   kind (dict, list of records, DataFrame, Arrow) would make it accurate.
2. **No check for duplicate keys.** `max_duplicate_rows` counts identical rows,
   so two orders sharing an `order_id` with different values pass. Key
   uniqueness is measured (`quality.metrics.uniqueness.key_uniqueness` when
   `identifier_columns` is given), but `check()` cannot gate on it:
   `require_metrics=["key_uniqueness"]` is rejected because only dimension
   names are accepted. A `max_duplicate_keys` or `min_key_uniqueness`
   requirement would close that gap.
3. **Two precisions for the same number.** `ColumnProfile.null_percentage` is
   full precision (10.2228...), while the matching `check()` row reports
   `observed: 10.22`. Both are correct, but a consumer joining the two sees a
   mismatch. Documenting the rounding on `QualityCheck.observed`, or exposing
   the unrounded value, would help.
4. **`profile_file()` has no `name=`** while `profile()` does, so scope labels
   for file-backed profiles have to be tracked outside the report.
5. **Native JSON is not byte-stable.** `to_json()` carries `id`, `timestamp` and
   execution timings, so re-profiling identical data produces a diff. A
   `deterministic=True` export (or a documented list of volatile keys) would
   make native outputs diffable in Git.
6. **Wall-clock-dependent metrics.** `timeliness.stale_data_ratio` and
   `future_dates_count` depend on when profiling runs, with no `as_of`
   parameter. For a dated snapshot an explicit reference date would make them
   reproducible.
7. **Slice profiling is left to the caller.** Profiling month and
   month x region scopes needs an adapter that groups rows and profiles each
   group. A `partition_by=[...]` option, or documentation of which column
   statistics are additive across disjoint partitions (counts, nulls) and
   which are not (unique counts, quantiles), would make the "sum counts, then
   divide" pattern explicit.

## This project

1. **`status` is not a usable DAX variable name.** Three measures failed with
   "the syntax for 'status' is incorrect" until the variable was renamed. The
   TMDL loaded without complaint; only `$SYSTEM.TMSCHEMA_MEASURES` (State 5,
   ErrorMessage) showed it. A pre-open lint that runs every measure through
   the engine, or simply querying that DMV after each load, catches this class
   of error early. `reconcile_live.py` would surface it indirectly as
   `SYNTAXERROR`.
2. **Locale leaks in three places.** Power Query parses with an explicit
   `en-US` culture, Python writes month names from a table rather than
   `strftime("%b")`, and the ADOMD reader formats `System.Decimal` with the
   invariant culture (it-IT renders `5571609,31`). Any new reader or writer
   needs the same care.
3. **Editing TMDL needs a Desktop reload.** Desktop does not watch the PBIP
   folder, so each TMDL edit meant closing and reopening the window, then a
   refresh. With the Power BI Authoring MCP connected, measure fixes can go to
   the live model directly and be saved back by Desktop, which shortens the
   loop considerably.
4. **Multi-region evidence (v2).** Two-region selections show "unavailable".
   Null and row counts are additive across disjoint region scopes, so a v2
   could sum the selected month x region rows (never the month row) and keep
   non-additive statistics unavailable.
5. **Day-level cross-filtering.** Evidence is month-grain. If a future visual
   lets users filter to individual days, the evidence still describes the
   whole month; the scope label says so, but a visual-interaction rule (or a
   guard measure) would make that explicit.
6. **PBIR rendering facts learned the hard way (Desktop 2.158).** Each was
   found from a screenshot, not from the schema, which accepts all of them:
   * Measure-driven colours (`dataPoint.fill` with a measure) work only with
     the wildcard-only selector `{"data": [{"dataViewWildcard": {"matchingOption": 1}}]}`;
     adding `metadata` silently disables them. With several series Desktop
     offers no measure colour at all, so the trend uses four mutually exclusive
     series with static colours.
   * The new card's callout value does not wrap (`value.textWrap` is ignored),
     `value.show: false` does not hide it, and it clips silently when reference
     labels below it need room. Reference-label values do wrap. The legacy card
     with `wordWrap` is the dependable way to show a sentence from a measure.
   * Cards print BLANK as "(Blank)"; text measures return `""` instead.
   * `LOOKUPVALUE` ignores filters on the table it searches, so lookups into
     the disconnected `Month Coverage` table are safe under month-axis clicks.
7. **Automate the visual check.** The reload, refresh, screenshot and crop loop
   (PowerShell `PrintWindow` plus a 16:9 crop) caught every layout defect
   above. Packaging it as a script with a pixel-diff against approved images
   would turn it into a regression test for the report.
8. **Like-for-like markers on the trend.** A marker series for days 1–N of
   every month would let readers compare September with earlier months on the
   same footing. It needs a combo chart with a shared axis; deferred because a
   second value axis would mislead.
9. **Snapshot history.** Only one snapshot exists. Keeping several
   `snapshot_id`s side by side (and a snapshot selector) would show how
   evidence changes as late data arrives, without implying dataprof stores
   history itself.
