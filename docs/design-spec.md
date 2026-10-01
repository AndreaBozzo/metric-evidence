# Metric Evidence: visual design spec

> **As built (differs from the spec below):**
> * The region contribution bars became a waterfall bridge (prior window → one step per region → current window).
> * A compact **Change by region, %** bar chart sits beside the bridge. It ranks the regions and is the right-click drillthrough handle, because waterfall steps cannot drill through.
> * The drillthrough carries only the region. The month syncs through the slicer, and the page stores no preset region.
> * The KPI card shows four callouts (selected period, comparison period, revenue change, orders change) and has no reference labels.
> * The trend uses four static-colour series instead of a colour measure. Desktop offers no measure colour once a chart has several series.
> * Sentences use legacy cards, which centre their text, because the new card does not wrap measure text.
> * The evidence panel is 464 px wide and is built from tinted adjoining visuals, not a visual group.
> * Page 2 has a month slicer synced with page 1.
>
> See `prep/author_report.py` for exact coordinates.

Status: implementation guide for hand-authored PBIR. Target: Power BI Desktop 2.158 (Sep 2026), native visuals only.
Theme file: `powerbi/theme/MetricEvidence.theme.json`. It validates with 0 errors against `reportThemeSchema-2.157.json`, the newest schema published (exploration version 5.76). No 2.158 schema has been published yet.

The report answers one question: **Revenue changed. Which segments contributed, and what data limitations affect the interpretation?**
Design rule behind every choice below: revenue direction and data-check status never share a color, a glyph or a sentence that reads as cause and effect.

---

## 1. Palette tokens

Surface for every chart is `bg.canvas` (#FFFFFF). Only evidence cards and text sit on `bg.panel`. Revenue-direction colors never appear on the panel.

| Token | Hex | Role | Contrast vs #FFFFFF | vs panel #F5F4F0 |
|---|---|---|---|---|
| `text.primary` | `#1E1E1C` | Titles, values, KPI numbers, category names | 16.70 | 15.17 |
| `text.secondary` | `#52514E` | Subtitles, axis and data labels, table headers | 7.94 | 7.21 |
| `text.muted` | `#6B6A65` | Footnotes, the "Unknown" row text, header icons | 5.42 | 4.92 |
| `bg.canvas` | `#FFFFFF` | Page and visual background | – | – |
| `bg.panel` | `#F5F4F0` | Evidence panel group, selected-month cell in tables | – | – |
| `bg.wallpaper` | `#EDECE7` | Outspace around the canvas | – | – |
| `line.grid` | `#E6E5E0` | Table row rules (chart gridlines are off) | 1.26 | – |
| `line.baseline` | `#C3C2B7` | Zero line in contribution chart, unselected slicer outline | 1.79 | – |
| `bar.context` | `#C4C2BA` | Unselected month, complete | 1.78 (relief: data labels) | – |
| `bar.contextPartial` | `#EEEDE8` | Unselected month, partial. Always carries the outline | 1.17 (relief: outline + label) | – |
| `bar.selected` | `#3A3935` | Selected month, complete; selected slicer button | 11.56 | – |
| `bar.selectedPartial` | `#8A8882` | Selected month, partial. Always carries the outline | 3.54 | – |
| `bar.partialOutline` | `#3A3935` | 1.5 px border on the partial-month series | 9.86 vs its pale fill | – |
| `dir.increase` | `#2A78D6` | Revenue increased (contribution bars only) | 4.42 | 4.01 |
| `dir.decrease` | `#EB6834` | Revenue decreased (contribution bars only) | 3.20 | 2.91 (do not use on panel) |
| `check.failed` | `#6A3D9A` | Check failed: glyph and text | 7.64 | 6.95 |
| `check.notEvaluated` | `#6B6A65` | Check not evaluated: glyph and text | 5.42 | 4.92 |
| `check.passed` | `#52514E` | Check passed: glyph and text. Kept neutral on purpose | 7.94 | 7.21 |
| `cat.unknown` | `#A3A19A` | "Unknown (label missing)" bar | 2.59 (relief: data label + axis label) | – |
| `cat.hardware` | `#0E8A73` | Hardware (teal) | 4.28 | – |
| `cat.software` | `#B07800` | Software (ochre) | 3.80 | – |
| `cat.services` | `#C2477F` | Services (rose) | 4.66 | – |
| `cat.accessories` | `#853E19` | Accessories (sienna) | 7.78 | – |

Hue ownership is exclusive: blue and orange mean direction, violet means the check failed, the four category hues mean identity, and charcoal and grays mean focus versus context. The report has **no red and no green**. A passed check uses neutral ink and a hollow glyph, so it never reads as "data is correct".

Status glyphs are part of the text measures, so status is never shown by color alone:
- `◆ Check failed`
- `◇ Check passed`
- `○ Not evaluated`
- Coverage: `◐ Partial month` and `● Complete month`

### Validator output (dataviz `validate_palette.js`, light mode, surface #FFFFFF)

| Run | Result |
|---|---|
| Categories, bar order H/S/Sv/A, adjacent pairs | **ALL PASS**: L band ✓, chroma ✓. Worst CVD ΔE 10.1 (ochre↔teal, protan). Worst normal-vision ΔE 18.3. Contrast is ≥3:1 for all four |
| Categories, all pairs (informational) | CVD **FAIL**: rose↔teal ΔE 2.3 (deutan). Normal-vision 17.7 ✓. This is acceptable because category identity sits on the labelled bar axis and color is redundant. Never use these four hues in a scatter or map |
| `dir.increase`, `dir.decrease`, `check.failed`, all pairs | **ALL PASS**. Worst CVD ΔE 11.7 (violet↔blue, deutan). Normal-vision ΔE 17.1. Contrast is ≥3:1 for all three |
| Trend states as an ordinal ramp (#EEEDE8 → #3A3935) | Monotone L ✓, step ΔL ✓, single hue ✓. Light-end contrast **FAIL** (1.17:1). This is mitigated by design: the partial series always has the 1.5 px charcoal outline and a data label |
| Unknown gray in the category set | Chroma **FAIL** and contrast WARN (2.59). Both are intended: Unknown must not read as a fifth category. Relief: its data label and axis label are always on |
| Text tokens (WCAG text contrast) | Every text color is ≥4.5:1 on both surfaces. The lowest is `text.muted` on the panel at 4.92 |

Dark mode is not shipped. A Power BI custom theme is single-mode, so only light mode was validated.

---

## 2. Typography

Fonts are Segoe UI and Segoe UI Semibold, both native in the Desktop font list. Sizes are in pt, as Power BI uses.

| Use | Font | Size | Color |
|---|---|---|---|
| Page title | Segoe UI Semibold | 18 | `text.primary` |
| Headline sentence (card callout) | Segoe UI | 13 | `text.primary` |
| Visual title | Segoe UI Semibold | 11 | `text.primary` |
| Visual subtitle | Segoe UI | 9 | `text.secondary` |
| KPI callout value | Segoe UI Semibold | 26 | `text.primary` |
| Evidence callout value | Segoe UI Semibold | 14 | `text.primary`, or fx for check status |
| Card labels and reference labels | Segoe UI (title in Semibold) | 9 | `text.secondary` / `text.primary` |
| Axis and data labels | Segoe UI | 9 | `text.secondary` |
| Category names on bar axes | Segoe UI | 10 | `text.primary` |
| Table header / body | Segoe UI Semibold / Segoe UI | 9 | `text.secondary` / `text.primary` |
| Slicer buttons | Segoe UI (Semibold when selected) | 10 | `text.primary` (white when selected) |
| Footnotes | Segoe UI | 8 | `text.muted` |

Copy rules:
- Use sentence case and no exclamation marks.
- Write numbers with a true minus sign: −8.5%, −$38K.
- Always name the comparison window, as in "Sep 1–20 vs Aug 1–20". Never write only "vs last month".

---

## 3. Layout grid (1280 × 720, both pages)

- Margins are 24 left and right, 16 top and bottom.
- There are 12 columns of 88 px with 16 px gutters. Column *i* (0-based) starts at x = 24 + 104·i, and a span of *n* columns is 104·n − 16 wide. Useful spans: 3 = 296, 4 = 400, 6 = 608, 9 = 920, 12 = 1232.
- The vertical rhythm is 8 px.
- The header band runs from y 16 to 112 and the body from y 128 to 704.
- Left content takes 9 columns (x 24, w 920). The evidence panel or slicers take 3 columns (x 960, w 296).
- There are no borders, no shadows and no decorative shapes. Whitespace groups the content. The only tint is `bg.panel` on the evidence group.
- Tab order is the same as reading order, numbered below. Every chart gets alt text through `general.altText`. Use the visual's question plus "Data labels show values".

### Page 1: "What changed?" (`what-changed`)

| # | Name | visualType | x | y | w | h |
|---|---|---|---|---|---|---|
| 1 | `txtTitle` | `textbox` | 24 | 16 | 600 | 32 |
| 2 | `cardHeadline` | `cardVisual` | 24 | 52 | 904 | 52 |
| 3 | `txtMonthLabel` | `textbox` | 960 | 16 | 296 | 16 |
| 4 | `slcMonth` | `advancedSlicerVisual` | 960 | 34 | 296 | 28 |
| 5 | `txtRegionLabel` | `textbox` | 960 | 66 | 296 | 16 |
| 6 | `slcRegion` | `advancedSlicerVisual` | 960 | 84 | 296 | 28 |
| 7 | `cardKpi` | `cardVisual` | 24 | 128 | 920 | 128 |
| 8 | `colTrend` | `columnChart` (stacked) | 24 | 272 | 920 | 232 |
| 9 | `barRegionContribution` | `clusteredBarChart` | 24 | 520 | 920 | 184 |
| 10 | `grpEvidence` (visual group) | group, `groupMode: ScaleMode` | 960 | 128 | 296 | 576 |
| 10a | `txtEvidenceHeading` | `textbox` | 976 | 144 | 264 | 20 |
| 10b | `txtEvidenceIntro` | `textbox` | 976 | 166 | 264 | 44 |
| 10c | `cardScope` | `cardVisual` | 976 | 218 | 264 | 52 |
| 10d | `cardCoverage` | `cardVisual` | 976 | 278 | 264 | 112 |
| 10e | `cardCompleteness` | `cardVisual` | 976 | 398 | 264 | 112 |
| 10f | `cardCheck` | `cardVisual` | 976 | 518 | 264 | 112 |
| 10g | `txtEvidenceFootnote` | `textbox` | 976 | 642 | 264 | 54 |

Reading order follows a Z path:
1. Headline (3-second answer).
2. KPI and trend (30-second context).
3. Region contributions (which segments).
4. Evidence panel (what limits the reading).
5. Drillthrough to page 2 (300-second detail).

Children of `grpEvidence` set `parentGroupName` and use background off (`show: false`) so the group fill shows through. The group sets `objects.background` to color #F5F4F0 with transparency 0. If group background proves unreliable, use one `shape` rectangle at the group's coordinates, filled #F5F4F0 with no outline, as the bottom layer, and exclude it from tab order.

### Page 2: "Segment detail" (`segment-detail`)

This is a drillthrough page on `Region[region_name]` with **Keep all filters on**, so the month selection carries over. Hide it in view mode (`HiddenInViewMode`) so it is only reached by drillthrough.

| # | Name | visualType | x | y | w | h |
|---|---|---|---|---|---|---|
| 1 | `btnBack` | `actionButton` (Back) | 24 | 20 | 28 | 28 |
| 2 | `txtTitle` | `textbox` | 60 | 16 | 560 | 32 |
| 3 | `cardHeadline` | `cardVisual` | 24 | 52 | 904 | 52 |
| 4 | `cardScope` | `cardVisual` (`bg.panel` background) | 960 | 16 | 296 | 96 |
| 5 | `colRevenueTrend` | `columnChart` (stacked) | 24 | 128 | 400 | 232 |
| 6 | `colOrdersTrend` | `columnChart` (stacked) | 440 | 128 | 400 | 232 |
| 7 | `barCategory` | `clusteredBarChart` | 856 | 128 | 400 | 232 |
| 8 | `tblEvidenceHistory` | `tableEx` | 24 | 376 | 608 | 264 |
| 9 | `tblCategoryDetail` | `tableEx` | 648 | 376 | 608 | 264 |
| 10 | `txtFootnote` | `textbox` | 24 | 656 | 1232 | 48 |

---

## 4. Per-visual specification

Measure names in `code` already exist in the model. Measures marked **(new)** are presentation measures to add. They return text or hex strings and should go in display folder `8 Presentation`.

### Presentation measures (new)

| Measure | Returns |
|---|---|
| `Headline What Changed` | One plain sentence, for example: "Revenue is down 8.5% like-for-like (Sep 1–20 vs Aug 1–20). North accounts for more than the whole decline; Central and South grew." It states contribution, never cause, and never mentions data quality. |
| `Revenue by Month (Complete)` / `Revenue by Month (Partial)` | `Revenue by Month` split by `'Month Coverage'[coverage_status]`, blank otherwise. Add the same pair for `Order Count by Month`. |
| `Trend Bar Color` | The selected month (its `month_key` = `Selected Month Key`) gets `#3A3935` if complete and `#8A8882` if partial. Other months get `#C4C2BA` if complete and `#EEEDE8` if partial. |
| `Change Direction Color` | `Revenue Change` < 0 → `#EB6834`; otherwise `#2A78D6`; blank → `#C4C2BA`. |
| `Category Color` | Hardware `#0E8A73`, Software `#B07800`, Services `#C2477F`, Accessories `#853E19`, Unknown `#A3A19A`. Key the mapping on `Category[category_key]`, not on the display name. |
| `Check Status Text` | `◆ Check failed`, `◇ Check passed` or `○ Not evaluated`, derived from `Evidence Category Check`. |
| `Check Status Color` | failed `#6A3D9A`, passed `#52514E`, not evaluated `#6B6A65`. |
| `Coverage Short` | `◐ Partial month · 20 of 30 days` or `● Complete month`. |
| `Evidence Means [Coverage/Completeness/Check]`, `Evidence Not Means [...]` | One sentence each, ≤ 85 characters (see 10d–10f). |
| `Contribution Subtitle` | "Change in revenue, Sep 1–20 vs Aug 1–20. Bars add up to the total change (−$X). Right-click a region for detail." |
| `Segment Headline` | "North: revenue −25.5% and orders −x% (Sep 1–20 vs Aug 1–20)." It contains facts only and no data-quality clause. |

### Page 1

**1 `txtTitle`.** Text "What changed?" in 18 pt Semibold.

**2 `cardHeadline`** answers "What is the one-sentence answer?"
- Values: `Headline What Changed`.
- Label off, reference labels off, accent bar off, background off.
- Callout is 13 pt Segoe UI with `textWrap: true`, left-aligned, display units none.
- Visual title off.

**3 / 5 labels.** Text "Month" and "Region · none selected = all regions" in 9 pt `text.secondary`.

**4 `slcMonth`** answers "Which month am I reading?"
- Field: `'Date'[month_short]`, sorted by `month_key`.
- `selection.singleSelect = true`, `strictSingleSelect = true` (force selection). The default selection is Sep.
- Layout: 1 row × 6 columns, Fit to space on.
- Button states come from the theme: white with a #C3C2B7 outline by default, and charcoal fill with white Semibold text when selected.
- Show "Sep" plainly. The partial flag lives in the trend axis and the evidence panel, not on the button.

**6 `slcRegion`** answers "Which region am I reading?"
- Field: `Region[region_name]`, sorted by `sort_order`.
- Single select on, force selection off. Clearing the selection means all regions.
- Layout: 1 row × 3 columns.

**7 `cardKpi`** answers "How much revenue, and how did it change on a like-for-like basis?"
- Title: "Revenue, like-for-like". Subtitle fx = `Comparison Note`, for example "Sep 1–20 vs Aug 1–20".
- Card A: label "Revenue, selected period", callout `Revenue (Comparable)` shown as $#,0. Reference label 1 has title "Comparison period" and value `Revenue (Prior Comparable)`.
- Card B: label "Change", callout `Revenue Change %` (+0.0%;−0.0%). Reference label 1 has title "In dollars" and value `Revenue Change` (+$#,0;−$#,0). Reference label 2 has title "Why this window" and the text "September data ends 20 Sep, so both months are cut at day 20."
- Callout numbers stay in `text.primary`. Do not color the KPI number by direction, because direction color is reserved for the contribution bars.
- Layout: horizontal, 2 cards, reference labels below the callout, background off.

**8 `colTrend`** answers "How does the selected month sit against the previous months?"
- Axis: `'Month Coverage'[trend_label]` ("Apr" … "Sep (1–20)"), sorted by `month_key`.
- Y values: `Revenue by Month (Complete)` and `Revenue by Month (Partial)`. Because they never overlap, stacking puts each month in one bar.
- Fill for both series is fx field value = `Trend Bar Color`.
- Partial series only: `dataPoint.borderShow = true`, `borderColor #3A3935`, `borderSize 1.5`, `borderColorMatchFill = false`. Border color has no fx in Desktop, which is why partial months need their own series.
- Data labels on, display units K, 9 pt `text.secondary`. Value axis off, gridlines off, legend off. Category axis 9 pt.
- Space between categories ≈ 40%.
- Title: "Monthly revenue, Apr–Sep 2026".
- Subtitle: "Dark = selected month. Outlined bar = partial month: September data ends 20 Sep, so its bar is short by construction."
- Interactions: the month slicer must not filter this visual. `Revenue by Month` already clears the `Date` filter. The region slicer does filter it.

**9 `barRegionContribution`** answers "Which regions contributed to the change, and in which direction?"
- Y: `Region[region_name]`. X: `Revenue Change`, sorted by `Revenue Change` ascending so the largest negative is on top.
- Fill is fx = `Change Direction Color`.
- Data labels show value (`Revenue Change`, K) plus detail (`Revenue Change %`) using the enhanced labels (`enableDetailDataLabel`). Labels are 9 pt `text.primary`.
- Analytics pane: constant line X = 0 in `#C3C2B7`, 1 px, no label.
- Value axis off, gridlines off, category axis 10 pt `text.primary`.
- Title: "Contribution to the revenue change, by region". Subtitle fx = `Contribution Subtitle`.
- Edit interactions: the region slicer → None (always show all three regions, ranked). The month slicer filters it.
- Direction is encoded three times: sign in the label, side of zero, and hue.

**10 `grpEvidence`** answers "What limits how far I can trust this reading?"
- **10a.** "Data limitations for this view", 11 pt Semibold.
- **10b.** "These describe the data behind the numbers. They are not reasons revenue changed." 9 pt `text.secondary`.
- **10c `cardScope`.** Label "Evidence scope", callout `Evidence Scope Label` ("Sep 2026 · North · snapshot through 20 Sep 2026") in 10 pt Semibold with wrap. No reference labels.
- **10d `cardCoverage`.** Label "Coverage", callout `Coverage Short` in 14 pt Semibold.
  - Reference label "Means": "September covers 1–20 Sep and is compared with Aug 1–20."
  - Reference label "Does not mean": "It is not a full-month result; full months would overstate the drop."
- **10e `cardCompleteness`.** Label "Category completeness (orders with a label)", callout `Evidence Category Completeness` (0.0%).
  - "Means": "10.2% of orders here have no category; they show as Unknown."
  - "Does not mean": "Revenue is not missing. These orders are still in every total."
- **10f `cardCheck`.** Label "dataprof check · missing labels ≤ 5%", callout `Check Status Text` with font color fx = `Check Status Color`.
  - When the check fails, "Means" is "Missing labels exceed the 5% allowance; category splits here are less reliable." "Does not mean" is "It does not explain why revenue changed."
  - When it passes, "Means" is "Missing labels are within the 5% allowance." "Does not mean" is "Passing is not proof the labels are correct." If no region is selected and any region fails, append: "North fails on its own (10.2%); select it."
  - When not evaluated, "Means" is "No check result exists for this scope." "Does not mean" is "No result is not a pass."
- All evidence cards: background off, accent bar off, reference-label background off, label 9 pt above the value, reference labels stacked vertically with title Semibold and value wrapping.
- **10g footnote.** "dataprof checks on the 20 Sep 2026 snapshot. Checks describe data quality; they are not causes of revenue change." 8 pt `text.muted`.

### Page 2

**1 `btnBack`.** Back action, icon only, icon color #52514E, no fill. Alt text "Back to What changed?".

**2 `txtTitle`.** "Segment detail".

**3 `cardHeadline`.** Values: `Segment Headline`, same format as page 1 #2.

**4 `cardScope`.** Background `bg.panel`. Label "Evidence scope", callout `Evidence Scope Label`. Reference label "Coverage" with value `Coverage Short`.

**5 `colRevenueTrend`** answers "How has this region's revenue moved by month?" It is identical in encoding to page 1 #8. Title: "Revenue by month". Subtitle: "Dark = selected month · outlined = partial month."

**6 `colOrdersTrend`** answers "Is the change in volume (orders) as well as value?"
- Same encoding, using `Order Count by Month (Complete/Partial)`. Labels #,0.
- Title: "Orders by month". Subtitle: "Same months and same partial-month rule as revenue."
- This is a separate chart, not a second axis.

**7 `barCategory`** answers "Which categories make up this region's revenue, and how much is unlabelled?"
- Y: `Category[category_name]`, sorted by `Category[sort_order]` with Unknown last. Do not sort by value, so Unknown always stays visible at the bottom.
- X: `Revenue (Comparable)`. Fill fx = `Category Color`.
- Data labels show value (K) plus detail = `Revenue Change %` vs comparison.
- Title: "Revenue by category, selected period". Subtitle fx: "Sep 1–20 · Unknown = orders without a category label; it grows when labelling fails, not only when sales change."

**8 `tblEvidenceHistory`** answers "How did the evidence look in each month?"
- Columns:
  - Month: `trend_label`
  - Revenue: `Revenue by Month`
  - Orders: `Order Count by Month`
  - Category completeness: `Category Completeness by Month`, 0.0%
  - Check: `Check Status Text` per month, font color fx = `Check Status Color`
  - Coverage: `Coverage Short`
- Highlight the selected month with cell background fx on the Month column, `#F5F4F0` for the selected month and none otherwise.
- Totals off. Horizontal rules #E6E5E0, no vertical rules, row padding 4.
- Title: "Evidence history, by month". Subtitle: "Completeness = share of orders with a category label. Allowance: missing ≤ 5%."

**9 `tblCategoryDetail`** answers "What are the exact numbers per category?" It doubles as the table view for accessibility.
- Columns: Category | Comparison period (`Revenue (Prior Comparable)`) | Selected period (`Revenue (Comparable)`) | Change $ | Change % | Orders.
- Unknown row font color fx `#6B6A65`. Totals on, in Semibold.
- Title: "Category detail". Subtitle fx = `Comparison Note`.

**10 `txtFootnote`.** "Comparison policy: a partial month is compared with the same days of the prior month. Category completeness and check results come from dataprof and describe the data, not the reasons revenue moved."

---

## 5. Theme JSON (`MetricEvidence.theme.json`): what it sets

- **`dataColors`:** charcoal, context gray, the four categories, Unknown, increase, decrease. Slot 1 is charcoal, so any new single-series chart defaults to "focus", never to a semantic hue. `check.failed` violet is deliberately left out of the data colors.
- **Sentiment and divergent colors:** `good` = increase blue, `bad` = decrease orange, `neutral` = gray. Divergent max, center and min are blue, #F0EFEC and orange.
- **`textClasses`:** see §2.
- **Defaults for all visuals:**
  - Title 11 pt Semibold and subtitle 9 pt, both left-aligned and wrapping.
  - Background white.
  - Border, shadow and divider off.
  - Padding 8.
  - Header icons: focus mode, options and "see data" stay on, because they give the table view. Pin, alert and Copilot buttons are off.
- **Charts:** legend off, value axis off, gridlines off, axis titles off, data labels on (9 pt, K units). Line charts are the exception: a light value axis and gridlines, for any future use.
- **`cardVisual`:** transparent, 26 pt callout, labels above the value, no accent bar, no reference-label background.
- **`advancedSlicerVisual`:** button background and outline per state through `$id: "default"` and `$id: "selection:selected"`. Header, title and padding off.
- **`tableEx`:** horizontal rules only, white rows (no banding), Semibold headers.
- **`page`:** white canvas, #EDECE7 wallpaper.

Wiring it in:
- The safest route is Desktop: View → Themes → Browse for themes. Desktop copies the file to `MetricEvidence.Report/StaticResources/RegisteredResources/`, registers it in `report.json` `resourcePackages`, and sets `themeCollection.customTheme`.
- Keep `themeCollection.baseTheme` on the current Fluent 2 base (`Fluent2-CY26SU08` is the newest name in schema 2.157). The custom theme overrides Fluent 2's grey canvas and rounded borders.
- Validation: the theme passed `jsonschema` Draft 7 against schema 2.157 with 0 errors. The schema does not reject unknown property names, so a separate key-by-key check against the schema's per-visual object lists was also run: 0 unknown keys.

---

## 6. Cutting-edge but native: what to use

1. **The card visual (GA Nov 2025) as the explanation surface** ([Learn: card visual](https://learn.microsoft.com/en-us/power-bi/visuals/power-bi-visualization-card)).
   - Each card can hold a callout, reference labels (title, value, detail) and fx conditional formatting.
   - Use it for the KPI, the headline sentence and the "means / does not mean" evidence cards.
   - In PBIR: `visualType: "cardVisual"`, with per-card settings through selectors. The theme sets `referenceLabel.backgroundShow: false` and `paddingUniform`, as the doc's own theme snippets do.
2. **Button slicer (GA) with forced single selection** ([Learn: button slicer](https://learn.microsoft.com/en-us/power-bi/visuals/power-bi-visualization-button-slicer)).
   - Use `advancedSlicerVisual` with `selection.singleSelect` and `strictSingleSelect`.
   - The selected state is styled in the theme via `$id: "selection:selected"`, so no bookmarks are needed.
   - Known limit: a forced selection hidden by another filter stays active, so keep the month slicer unfiltered by other visuals.
3. **Expression-based titles and subtitles, and measure-driven colors** ([Learn: expression-based titles](https://learn.microsoft.com/en-us/power-bi/create-reports/desktop-conditional-format-visual-titles); [SQLBI: visual calculations for conditional formatting](https://www.sqlbi.com/articles/using-visual-calculations-for-conditional-formatting/)).
   - The comparison window ("Sep 1–20 vs Aug 1–20") always shows in the subtitle.
   - Bar fills come from hex-returning measures.
   - Visual calculations are GA since May 2026 ([Power BI May 2026 feature summary](https://community.fabric.microsoft.com/blog/fbc_pbiupdatesblog/power-bi-may-2026-feature-summary/5182174)). They are fine for local logic, but the selection-aware colors here belong in model measures because three visuals reuse them. If a visual calculation returns a color string, set its data type to Text (SQLBI caveat).
4. **Enhanced data labels and axis behavior instead of axes and gridlines.**
   - Use title/value/detail labels on bar and column charts (`labels.enableDetailDataLabel`, `dynamicLabelDetail`).
   - Since June 2026, data labels no longer shift the axis, and "Rounded range" can be turned off ([June 2026 summary](https://community.fabric.microsoft.com/blog/fbc_pbiupdatesblog/power-bi-june-2026-feature-summary/5193264)). Outer padding is GA since Aug 2026 ([Learn: what's new](https://learn.microsoft.com/en-us/power-bi/fundamentals/whats-new)).
   - This is the Datawrapper/FT approach: label the data and drop the scaffolding ([Datawrapper: text in data visualizations](https://www.datawrapper.de/blog/text-in-data-visualizations)).
5. **Layout by the 3-30-300 rule, with a theme on Fluent 2** ([SQLBI: 3-30-300](https://www.sqlbi.com/articles/introducing-the-3-30-300-rule-for-better-reports/); [Learn: visual defaults / Fluent 2](https://learn.microsoft.com/en-us/power-bi/create-reports/power-bi-reports-visual-defaults)).
   - The headline gives the answer in 3 seconds, KPI, trend and contributions give the pattern in 30, and drillthrough gives the detail in 300.
   - The Theme pane and modern visual defaults are GA since Aug 2026, and a custom theme layers over the base theme.
   - Annotation caution, from Data Goblins: dynamic annotations can stop fitting the data after the user filters, and can suggest an explanation that is not true for every selection ([Data Goblins report checklist](https://data-goblins.com/power-bi/report-checklist)). Every sentence here is therefore a measure with explicit branches, and none states a cause.

**Avoid:**
- **List slicer.** Still preview ([Learn](https://learn.microsoft.com/en-us/power-bi/visuals/power-bi-visualization-list-slicer)).
- **Narrative visual "value selection".** Preview in Sep 2026.
- **Copilot narrative or summary.** Generated text can attribute causes.
- **Pattern fills.** The `fill.pattern` node is in the theme schema but has no documented UI, so do not rely on it.
- **Border color via fx.** Not supported; use the two-series trick instead.
- **Gauges, the KPI visual, dual-axis combos and decorative bookmarks.**
- **Deneb.** Not needed. The one candidate, a hatched partial-month bar, is covered natively by the outlined partial series.

---

## 7. Two decisions to review personally

1. **The trend still shows a short September bar.** Even outlined and labelled "Sep (1–20)", a 20-day bar next to 30-day bars invites exactly the naive full-month reading (−39.8%) that the comparison policy prevents.
   - The alternative is to add a "days 1–20 of each month" series as markers on the same axis (`lineStackedColumnComboChart`, line width 0, markers 8 px, `text.primary`). Every month then has a like-for-like point and Aug 1–20 vs Sep 1–20 can be read directly. Another option is to plot only the days 1–20 values.
   - Doing either changes what the trend says, so it needs an owner's call.
2. **How the check status is encoded.**
   - "Failed" is violet `◆`, "passed" is deliberately understated (neutral ink, hollow `◇`), and there is no red or green anywhere.
   - Review whether violet reads as "attention, not alarm" for your audience.
   - Also review whether understating "passed" is right when the all-regions view passes (4.7%) while North fails (10.2%). The check card adds a sentence for that case, but the passing aggregate is still what a reader sees first.

Smaller call, noted but not flagged: category bars are colored by category, which is redundant with the axis labels. This is kept because the brief asks for category colors and because it separates Unknown (gray) from real categories at a glance. A single-hue variant (all four categories `#3A3935`, Unknown `#A3A19A`) is equally valid.
