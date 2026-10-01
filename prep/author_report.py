"""Write the two report pages as PBIR JSON (initial authoring).

The layout, colors and wording follow docs/design-spec.md. After the report has
been edited in Power BI Desktop, the PBIR files are the source of truth: this
script refuses to overwrite existing pages unless --overwrite is given.

Usage: uv run python prep/author_report.py [--overwrite]
"""

from __future__ import annotations

import argparse
import json
import shutil
import uuid
from pathlib import Path

from paths import REPO_ROOT, desktop_bin

REPORT = REPO_ROOT / "powerbi" / "MetricEvidence.Report"
THEME_SRC = REPO_ROOT / "powerbi" / "theme" / "MetricEvidence.theme.json"
DESKTOP_BASE_THEMES = desktop_bin() / "WebView2Resources" / "minerva" / "sharedresources" / "BaseThemes"
BASE_THEME = "Fluent2-CY26SU09"
THEME_FILE = "MetricEvidence.theme.json"
VERSION_AT_IMPORT = {"visual": "2.12.0", "report": "3.4.0", "page": "2.3.1"}

SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/"
VC_SCHEMA = SCHEMA + "visualContainer/2.12.0/schema.json"

# Palette tokens (docs/design-spec.md section 1)
TEXT, TEXT_2, TEXT_MUTED = "#1E1E1C", "#52514E", "#6B6A65"
PANEL, BASELINE, OUTLINE = "#F5F4F0", "#C3C2B7", "#3A3935"
SEMIBOLD = "'''Segoe UI Semibold'', wf_segoe-ui_semibold, helvetica, arial, sans-serif'"
REGULAR = "'''Segoe UI'', wf_segoe-ui_normal, helvetica, arial, sans-serif'"

# ---------------------------------------------------------------- expressions


def lit(value) -> dict:
    """A formatting literal: str -> 'text', bool -> true, int -> 1L, float -> 1.5D."""
    if isinstance(value, bool):
        v = "true" if value else "false"
    elif isinstance(value, int):
        v = f"{value}L"
    elif isinstance(value, float):
        v = f"{value:g}D"
    else:
        v = "'" + str(value).replace("'", "''") + "'"
    return {"expr": {"Literal": {"Value": v}}}


def num(value: float) -> dict:
    return {"expr": {"Literal": {"Value": f"{value:g}D"}}}


def font(name: str) -> dict:
    return {"expr": {"Literal": {"Value": name}}}


def col(entity: str, prop: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def meas(entity: str, prop: str) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def color(hex_or_measure) -> dict:
    expr = lit(hex_or_measure)["expr"] if isinstance(hex_or_measure, str) else hex_or_measure
    return {"solid": {"color": {"expr": expr}}}


def mexpr(entity: str, prop: str) -> dict:
    return {"expr": meas(entity, prop)}


def ref(field: dict) -> str:
    inner = field.get("Column") or field.get("Measure")
    return f"{inner['Expression']['SourceRef']['Entity']}.{inner['Property']}"


def proj(field: dict, display: str | None = None) -> dict:
    p = {"field": field, "queryRef": ref(field), "nativeQueryRef": (field.get("Column") or field.get("Measure"))["Property"]}
    if display:
        p["displayName"] = display
    return p


WILDCARD = {"data": [{"dataViewWildcard": {"matchingOption": 1}}]}


def props(**kw) -> list[dict]:
    return [{"properties": kw}]


# Fields used below
ORD, E, MC = "Orders", "Evidence Column Stats", "Month Coverage"
F = {
    "month_short": col("Date", "month_short"),
    "region_name": col("Region", "region_name"),
    "category_name": col("Category", "category_name"),
    "trend_label": col(MC, "trend_label"),
    "month_key_mc": col(MC, "month_key"),
}


def m(name: str, entity: str = ORD) -> dict:
    return meas(entity, name)


# ---------------------------------------------------------------- containers


def container(name: str, x, y, w, h, visual: dict, *, z: int, alt: str | None = None,
              title: str | dict | None = None, subtitle: str | dict | None = None,
              background: str | None = None) -> dict:
    vco: dict = {}
    if title is None:
        vco["title"] = props(show=lit(False))
    else:
        vco["title"] = props(show=lit(True), text=title if isinstance(title, dict) else lit(title))
    if subtitle is not None:
        vco["subTitle"] = props(show=lit(True), text=subtitle if isinstance(subtitle, dict) else lit(subtitle))
    if background:
        vco["background"] = props(show=lit(True), color=color(background), transparency=num(0))
    if alt:
        vco["general"] = props(altText=lit(alt))
    visual = dict(visual)
    visual["visualContainerObjects"] = {**vco, **visual.get("visualContainerObjects", {})}
    visual.setdefault("drillFilterOtherVisuals", True)
    return {"$schema": VC_SCHEMA, "name": name,
            "position": {"x": x, "y": y, "z": z, "width": w, "height": h, "tabOrder": z},
            "visual": visual}


def textbox(paragraphs: list[list[tuple[str, str, int, str]]], align: str | None = None) -> dict:
    """paragraphs: list of runs (text, font family, size pt, color)."""
    families = {"semibold": "Segoe UI Semibold", "regular": "Segoe UI"}
    return {
        "visualType": "textbox",
        "objects": {"general": [{"properties": {"paragraphs": [
            {"textRuns": [{"value": t, "textStyle": {"fontFamily": families[f], "fontSize": f"{s}pt", "color": c}}
                          for t, f, s, c in runs], **({"horizontalTextAlignment": align} if align else {})}
            for runs in paragraphs]}}]},
    }


def _field_id(card: str, i: int) -> str:
    return "field-" + str(uuid.uuid5(uuid.NAMESPACE_URL, f"metric-evidence/{card}/{i}"))


def card(name: str, values: list[tuple[dict, str]], *, value_size: float, value_font=SEMIBOLD,
         label: bool = True, refs: dict[int, list[tuple[str, dict]]] | None = None,
         value_color: dict | None = None, columns: int = 1, wrap: bool = True,
         callout_size: float | None = None, refs_position: str = "below") -> dict:
    """New card visual. values: (field, label). refs: card index -> [(title, measure field)]."""
    projections = [proj(f, lbl) for f, lbl in values]
    objects: dict = {
        "layout": props(style=lit("Cards"), alignment=lit("top"),
                        **({"columnCount": lit(columns), "rowCount": lit(1)} if columns > 1 else {}),
                        **({"calloutSize": num(callout_size)} if callout_size else {})),
        "value": [{"properties": {"fontSize": num(value_size), "fontFamily": font(value_font),
                                  "horizontalAlignment": lit("left"), "textWrap": lit(wrap),
                                  "labelDisplayUnits": num(1)}, "selector": {"id": "default"}}],
        "label": [{"properties": {"show": lit(label), "position": lit("aboveValue")}, "selector": {"id": "default"}}],
        "accentBar": [{"properties": {"show": lit(False)}, "selector": {"id": "default"}}],
        "outline": [{"properties": {"show": lit(False)}, "selector": {"id": "default"}}],
    }
    if value_color is not None:
        objects["value"].append({"properties": {"fontColor": color(value_color)},
                                 "selector": {"metadata": projections[0]["queryRef"]}})
    for idx, items in (refs or {}).items():
        target = projections[idx]["queryRef"]
        for order, (title, field) in enumerate(items):
            fid = _field_id(name, idx * 10 + order)
            objects.setdefault("referenceLabel", []).append({
                "properties": {"value": {"expr": field}},
                "selector": {"data": [{"dataViewWildcard": {"matchingOption": 0}}], "metadata": target,
                             "id": fid, "order": order}})
            objects.setdefault("referenceLabelTitle", []).append({
                "properties": {"show": lit(True), "titleContentType": lit("custom"), "titleText": lit(title)},
                "selector": {"metadata": target, "id": fid}})
            objects.setdefault("referenceLabelValue", []).append({
                "properties": {"textWrap": lit(True)}, "selector": {"metadata": target, "id": fid}})
            objects.setdefault("referenceLabelDetail", []).append({
                "properties": {"show": lit(False)}, "selector": {"metadata": target, "id": fid}})
        objects.setdefault("referenceLabelLayout", []).append({
            "properties": {"position": lit(refs_position), "arrangement": lit("rows"), "style": lit("sentence")},
            "selector": {"metadata": target}})
    return {"visualType": "cardVisual",
            "query": {"queryState": {"Data": {"projections": projections}}},
            "objects": objects}


def sentence_card(name: str, field: dict, *, size: float, title: str | None = None,
                  color_hex: str = TEXT) -> dict:
    """Long text from a measure. In Desktop 2.158 neither the new card's callout nor the
    multi-row card wraps, so sentences use the legacy card with word wrap (text is centred)."""
    return {"visualType": "card",
            "query": {"queryState": {"Values": {"projections": [proj(field, title)]}}},
            "objects": {
                "labels": props(fontSize=num(size), color=color(color_hex)),
                "categoryLabels": props(show=lit(title is not None), fontSize=num(9), color=color(TEXT_2)),
                "wordWrap": props(show=lit(True)),
            }}


def slicer(field: dict, *, strict: bool, columns: int, default: str | None = None,
           sync: str | None = None) -> dict:
    objects: dict = {
        "selection": props(singleSelect=lit(True), strictSingleSelect=lit(strict)),
        "layout": props(style=lit("Cards"), columnCount=lit(columns), rowCount=lit(1), cellPadding=lit(2)),
        "value": [{"properties": {"fontSize": num(10), "horizontalAlignment": lit("center")}, "selector": {"id": "default"}}],
    }
    if default is not None:
        inner = field["Column"]
        objects["general"] = [{"properties": {"filter": {"filter": {
            "Version": 2,
            "From": [{"Name": "s", "Entity": inner["Expression"]["SourceRef"]["Entity"], "Type": 0}],
            "Where": [{"Condition": {"In": {
                "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "s"}}, "Property": inner["Property"]}}],
                "Values": [[{"Literal": {"Value": f"'{default}'"}}]]}}}]}}}}]
    visual = {"visualType": "advancedSlicerVisual",
              "query": {"queryState": {"Values": {"projections": [proj(field)]}}},
              "objects": objects}
    if sync:
        visual["syncGroup"] = {"groupName": sync, "fieldChanges": True, "filterChanges": True}
    return visual


def trend(prefix: str, *, units: float) -> dict:
    """Stacked columns from four mutually exclusive series (selected / other months, each
    complete or partial), so every month is one bar. Desktop offers no measure-driven
    colour once a chart has several series, so each series carries a static colour and
    only the partial ones get the outline."""
    series = [(f"{prefix}, other months", "#C4C2BA", False), (f"{prefix}, selected month", "#3A3935", False),
              (f"{prefix}, partial month", "#EEEDE8", True), (f"{prefix}, selected partial month", "#8A8882", True)]
    projections = [proj(m(name)) for name, _, _ in series]
    data_point = []
    for p, (_, fill, outlined) in zip(projections, series, strict=True):
        style = {"fill": color(fill)}
        if outlined:
            style.update(borderShow=lit(True), borderColor=color(OUTLINE), borderSize=num(1.5),
                         borderColorMatchFill=lit(False))
        data_point.append({"properties": style, "selector": {"metadata": p["queryRef"]}})
    return {
        "visualType": "columnChart",
        "query": {"queryState": {"Category": {"projections": [proj(F["trend_label"])]},
                                 "Y": {"projections": projections}},
                  "sortDefinition": {"sort": [{"field": F["trend_label"], "direction": "Ascending"}],
                                     "isDefaultSort": True}},
        "objects": {
            "dataPoint": data_point,
            "labels": props(show=lit(False)),
            "totals": props(show=lit(True), fontSize=num(9), color=color(TEXT_2),
                            labelDisplayUnits=num(units), labelPrecision=lit(0)),
            "legend": props(show=lit(False)),
            "valueAxis": props(show=lit(False), gridlineShow=lit(False)),
            "categoryAxis": props(show=lit(True), showAxisTitle=lit(False), fontSize=num(9),
                                  labelColor=color(TEXT_2), gridlineShow=lit(False)),
        },
    }


def hbar(category: dict, value: dict, *, fill: dict, sort: tuple[dict, str], units: float) -> dict:
    v = proj(value)
    return {
        "visualType": "clusteredBarChart",
        "query": {"queryState": {"Category": {"projections": [proj(category)]}, "Y": {"projections": [v]}},
                  "sortDefinition": {"sort": [{"field": sort[0], "direction": sort[1]}], "isDefaultSort": False}},
        "objects": {
            # Measure-driven fill needs the wildcard-only selector (no metadata).
            "dataPoint": [{"properties": {}}, {"properties": {"fill": color(fill)}, "selector": WILDCARD}],
            "labels": props(show=lit(True), fontSize=num(9), color=color(TEXT), labelDisplayUnits=num(units),
                            labelPrecision=lit(1)),
            "legend": props(show=lit(False)),
            "valueAxis": props(show=lit(False), gridlineShow=lit(False)),
            "categoryAxis": props(show=lit(True), showAxisTitle=lit(False), fontSize=num(10), labelColor=color(TEXT)),
        },
    }


def waterfall(category: dict, breakdown: dict, value: dict, *, units: float) -> dict:
    """Native waterfall with a breakdown: the two compared periods are the totals and each
    breakdown member is one step between them."""
    return {
        "visualType": "waterfallChart",
        "query": {"queryState": {"Category": {"projections": [proj(category)]},
                                 "Breakdown": {"projections": [proj(breakdown)]},
                                 "Y": {"projections": [proj(value)]}},
                  "sortDefinition": {"sort": [{"field": category, "direction": "Ascending"}], "isDefaultSort": True}},
        "objects": {
            "sentimentColors": props(increaseFill=color("#2A78D6"), decreaseFill=color("#EB6834"),
                                     totalFill=color("#8A8882"), otherFill=color("#C4C2BA")),
            "breakdown": props(maxBreakdowns=lit(5)),
            "labels": props(show=lit(True), fontSize=num(9), color=color(TEXT), labelDisplayUnits=num(units),
                            labelPrecision=lit(1)),
            "legend": props(show=lit(False)),
            "valueAxis": props(show=lit(False), gridlineShow=lit(False)),
            "categoryAxis": props(show=lit(True), showAxisTitle=lit(False), fontSize=num(10), labelColor=color(TEXT)),
        },
    }


def table(columns: list[tuple[dict, str]], *, totals: bool, font_rules: list[tuple[dict, dict]] = (),
          back_rules: list[tuple[dict, dict]] = ()) -> dict:
    projections = [proj(f, lbl) for f, lbl in columns]
    values = []
    for target, measure in font_rules:
        values.append({"properties": {"fontColor": color(measure)}, "selector": {**WILDCARD, "metadata": ref(target)}})
    for target, measure in back_rules:
        values.append({"properties": {"backColor": color(measure)}, "selector": {**WILDCARD, "metadata": ref(target)}})
    objects: dict = {"total": props(totals=lit(totals))}
    if values:
        objects["values"] = values
    return {"visualType": "tableEx", "query": {"queryState": {"Values": {"projections": projections}}},
            "objects": objects}


# ---------------------------------------------------------------- pages


def page_what_changed(region: str | None = None) -> tuple[dict, list[dict]]:
    v = []
    z = iter(range(0, 100000, 1000))
    v.append(container("txtTitle", 24, 14, 620, 34, z=next(z), visual=textbox(
        [[("What changed?", "semibold", 18, TEXT),
          ("    Metric Evidence · synthetic orders · snapshot through 20 Sep 2026", "regular", 9, TEXT_MUTED)]])))
    v.append(container("cardHeadline", 24, 52, 752, 34, z=next(z),
                       visual=sentence_card("cardHeadline", m("Headline What Changed"), size=13)))
    v.append(container("cardHeadline2", 24, 84, 752, 30, z=next(z),
                       visual=sentence_card("cardHeadline2", m("Headline Contribution"), size=11, color_hex=TEXT_2)))
    v.append(container("txtMonthLabel", 648, 20, 52, 20, z=next(z), visual=textbox(
        [[("Month", "regular", 9, TEXT_2)]])))
    v.append(container("slcMonth", 704, 14, 552, 34, z=next(z), alt="Month selector, one month at a time",
                       visual=slicer(F["month_short"], strict=True, columns=6, default="Sep", sync="month")))
    v.append(container("txtRegionLabel", 792, 54, 464, 20, z=next(z), visual=textbox(
        [[("Region · none selected = all regions", "regular", 9, TEXT_2)]])))
    v.append(container("slcRegion", 792, 74, 464, 34, z=next(z), alt="Region selector; clear it for all regions",
                       visual=slicer(F["region_name"], strict=False, columns=3, default=region)))
    v.append(container(
        "cardKpi", 24, 128, 752, 120, z=next(z), title=mexpr(ORD, "KPI Title"),
        alt="Revenue for the selected period and its change against the comparable prior period.",
        visual=card("cardKpi", [(m("Revenue (Comparable)"), "Selected period"),
                                (m("Revenue (Prior Comparable)"), "Comparison period"),
                                (m("Revenue Change %"), "Revenue change"),
                                (m("Order Change %"), "Orders change")],
                    value_size=22, columns=4, wrap=False)))
    v.append(container(
        "colTrend", 24, 264, 752, 240, z=next(z), title="Monthly revenue, Apr–Sep 2026",
        subtitle="Dark = selected month. Outlined bar = partial month: September data ends 20 Sep, so its bar is short by construction.",
        alt="Monthly revenue from April to September 2026; the September bar covers 1 to 20 September only. Data labels show values.",
        visual=trend("Revenue", units=1000.0)))
    v.append(container(
        "barRegionContribution", 24, 520, 544, 184, z=next(z),
        title=mexpr(ORD, "Bridge Title"), subtitle=mexpr(ORD, "Contribution Subtitle"),
        alt="Revenue bridge from the comparison period to the selected period, one step per region. Data labels show values.",
        visual=waterfall(F["trend_label"], F["region_name"], m("Bridge Revenue"), units=1000.0)))
    # Waterfall breakdown points offer no drillthrough, so the ranked % bars are the
    # right-click handle for the segment page (Region is their category).
    v.append(container(
        "barRegionChange", 584, 520, 192, 184, z=next(z),
        title="Change by region, %", subtitle="Right-click a region → Drill through for detail.",
        alt="Revenue change percentage by region, ranked. Right-click a region to drill through to its detail page.",
        visual=hbar(F["region_name"], m("Revenue Change %"), fill=mexpr(ORD, "Change Direction Color")["expr"],
                    sort=(m("Revenue Change %"), "Ascending"), units=1.0)))
    # Evidence panel: contiguous tinted visuals from y 128 to 704.
    v.append(container("txtEvidenceHeading", 792, 124, 464, 44, z=next(z), background=PANEL, visual=textbox([
        [("Data limitations for this view", "semibold", 11, TEXT)],
        [("Facts about the data, not reasons revenue changed.", "regular", 9, TEXT_2)],
    ])))
    v.append(container("cardScope", 792, 168, 464, 32, z=next(z), background=PANEL, visual=sentence_card(
        "cardScope", m("Evidence Scope Label", E), size=10)))
    v.append(container("cardCoverage", 792, 200, 464, 168, z=next(z), background=PANEL, visual=card(
        "cardCoverage", [(m("Coverage Short", E), "Coverage (from the extract definition)")], value_size=13, callout_size=40.0,
        refs={0: [("Means:", m("Coverage Means", E)), ("Does not mean:", m("Coverage Not Means", E))]})))
    v.append(container("cardCompleteness", 792, 368, 464, 160, z=next(z), background=PANEL, visual=card(
        "cardCompleteness", [(m("Evidence Category Completeness", E), "Category completeness (orders with a label)")],
        value_size=13, callout_size=40.0,
        refs={0: [("Means:", m("Completeness Means", E)), ("Does not mean:", m("Completeness Not Means", E))]})))
    v.append(container("cardCheck", 792, 528, 464, 176, z=next(z), background=PANEL, visual=card(
        "cardCheck", [(m("Check Status Text", E), "dataprof 0.12.0 check · missing labels ≤ 5%")], value_size=13, callout_size=40.0,
        value_color=mexpr(E, "Check Status Color")["expr"],
        refs={0: [("Means:", m("Check Means", E)), ("Does not mean:", m("Check Not Means", E))]})))

    names = [x["name"] for x in v]
    # Month-axis visuals filter the disconnected Month Coverage table: never let that
    # reach visuals that read the selected month.
    interactions = [{"source": "colTrend", "target": t, "type": "NoFilter"} for t in names if t != "colTrend"]
    # The contribution chart always ranks all three regions.
    interactions.append({"source": "slcRegion", "target": "barRegionContribution", "type": "NoFilter"})
    interactions.append({"source": "slcRegion", "target": "barRegionChange", "type": "NoFilter"})
    interactions.append({"source": "barRegionContribution", "target": "colTrend", "type": "DataFilter"})
    page = {"$schema": SCHEMA + "page/2.1.0/schema.json", "name": "what-changed", "displayName": "What changed?",
            "displayOption": "FitToPage", "height": 720, "width": 1280, "visualInteractions": interactions}
    return page, v


def page_segment_detail() -> tuple[dict, list[dict]]:
    v = []
    z = iter(range(0, 100000, 1000))
    v.append(container("btnBack", 16, 14, 40, 36, z=next(z), alt="Back to What changed?", visual={
        "visualType": "actionButton",
        "objects": {"icon": [{"properties": {"show": lit(True), "shapeType": lit("back"), "lineColor": color(TEXT_2),
                                             "lineWeight": num(2), "iconSize": num(20)},
                              "selector": {"id": "default"}}],
                    "fill": [{"properties": {"show": lit(False)}},
                             {"properties": {"show": lit(False)}, "selector": {"id": "default"}}]},
        "visualContainerObjects": {"visualLink": props(show=lit(True), type=lit("Back"))},
    }))
    v.append(container("txtTitle", 60, 16, 360, 32, z=next(z), visual=textbox([[("Segment detail", "semibold", 18, TEXT)]])))
    v.append(container("slcMonth", 440, 14, 488, 34, z=next(z), alt="Month selector, synced with the first page",
                       visual=slicer(F["month_short"], strict=True, columns=6, default="Sep", sync="month")))
    v.append(container("cardHeadline", 24, 52, 904, 64, z=next(z),
                       visual=sentence_card("cardHeadline2", m("Segment Headline"), size=13)))
    v.append(container("txtScopeCaption", 960, 12, 296, 24, z=next(z), background=PANEL, visual=textbox(
        [[("Evidence scope", "regular", 9, TEXT_2)]], align="center")))
    v.append(container("cardScope", 960, 36, 296, 36, z=next(z), background=PANEL, visual=sentence_card(
        "cardScope2", m("Evidence Scope Label", E), size=10)))
    v.append(container("cardEvidenceSummary", 960, 72, 296, 40, z=next(z), background=PANEL, visual=sentence_card(
        "cardEvidenceSummary", m("Evidence Summary", E), size=10, color_hex=TEXT_2)))
    v.append(container("colRevenueTrend", 24, 128, 400, 232, z=next(z), title="Revenue by month",
                       subtitle="Dark = selected month · outlined = partial month.",
                       alt="Monthly revenue for this region. Data labels show values.",
                       visual=trend("Revenue", units=1000.0)))
    v.append(container("colOrdersTrend", 440, 128, 400, 232, z=next(z), title="Orders by month",
                       subtitle="Same months and same partial-month rule as revenue.",
                       alt="Monthly order count for this region. Data labels show values.",
                       visual=trend("Orders", units=1.0)))
    v.append(container("barCategory", 856, 128, 400, 232, z=next(z), title="Revenue by category, selected period",
                       subtitle=mexpr(ORD, "Category Subtitle"),
                       alt="Revenue by category including Unknown for the selected period. Data labels show values.",
                       visual=hbar(F["category_name"], m("Revenue (Comparable)"),
                                   fill=mexpr(ORD, "Category Color")["expr"], sort=(F["category_name"], "Ascending"),
                                   units=1000.0)))
    v.append(container("tblEvidenceHistory", 24, 376, 608, 264, z=next(z), title="Evidence history, by month",
                       subtitle="Completeness = share of orders with a category label (dataprof). Allowance: missing ≤ 5%.",
                       alt="Month by month revenue, orders, category completeness, dataprof check and coverage.",
                       visual=table([
                           (F["trend_label"], "Month"),
                           (m("Revenue by Month"), "Revenue"),
                           (m("Order Count by Month"), "Orders"),
                           (m("Evidence Category Completeness", E), "Category completeness"),
                           (m("Check Status Text", E), "Check"),
                           (m("Coverage Short", E), "Coverage"),
                       ], totals=False,
                           font_rules=[(m("Check Status Text", E), mexpr(E, "Check Status Color")["expr"])],
                           back_rules=[(F["trend_label"], mexpr(ORD, "Selected Month Background")["expr"])])))
    v.append(container("tblCategoryDetail", 648, 376, 608, 264, z=next(z), title="Category detail",
                       subtitle=mexpr(ORD, "Comparison Note"),
                       alt="Exact revenue, change and orders per category, including Unknown.",
                       visual=table([
                           (F["category_name"], "Category"),
                           (m("Revenue (Prior Comparable)"), "Comparison period"),
                           (m("Revenue (Comparable)"), "Selected period"),
                           (m("Revenue Change"), "Change"),
                           (m("Revenue Change %"), "Change %"),
                           (m("Order Count (Comparable)"), "Orders"),
                       ], totals=True,
                           font_rules=[(F["category_name"], mexpr(ORD, "Category Row Font Color")["expr"])])))
    v.append(container("cardSnapshot", 24, 616, 904, 32, z=next(z), visual=sentence_card(
        "cardSnapshot", m("Snapshot Consistency", E), size=9, color_hex=TEXT_MUTED)))
    v.append(container("txtFootnote", 24, 656, 1232, 48, z=next(z), visual=textbox([[(
        "Comparison policy (a simple demo policy, not seasonally adjusted): a partial month is compared with the same days "
        "of the prior month, a complete month with the full prior month. Category completeness and check results come from "
        "dataprof and describe the data, not the reasons revenue moved.",
        "regular", 8, TEXT_MUTED)]])))

    names = [x["name"] for x in v]
    interactions = [{"source": s, "target": t, "type": "NoFilter"}
                    for s in ("colRevenueTrend", "colOrdersTrend", "tblEvidenceHistory") for t in names if t != s]
    drill_filter = "drillRegion"
    page = {
        "$schema": SCHEMA + "page/2.1.0/schema.json", "name": "segment-detail", "displayName": "Segment detail",
        "displayOption": "FitToPage", "height": 720, "width": 1280,
        # No saved drill value: opened directly the page shows all regions, so a broken
        # drillthrough cannot hide behind a preset region.
        "filterConfig": {"filters": [{"name": drill_filter, "field": F["region_name"], "type": "Categorical",
                                      "howCreated": "Drillthrough"}]},
        # Drillthrough carries only the region. The month travels through the synced month
        # slicer, so it stays changeable here; "keep all filters" would pin it to one value.
        "pageBinding": {"name": "drillRegionBinding", "type": "Drillthrough", "acceptsFilterContext": "None",
                        "parameters": [{"name": "drillRegionParam", "boundFilter": drill_filter,
                                        "fieldExpr": F["region_name"]}]},
        "type": "Drillthrough",
        "visibility": "HiddenInViewMode",
        "visualInteractions": interactions,
    }
    return page, v


# ---------------------------------------------------------------- report


def write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true")
    # Only for reproducing README screenshots; the defaults are the shipped state.
    parser.add_argument("--region", help="initial region slicer selection (default: none = all regions)")
    parser.add_argument("--active-page", choices=["what-changed", "segment-detail"], default="what-changed")
    args = parser.parse_args()
    pages_dir = REPORT / "definition" / "pages"
    built = [page_what_changed(args.region), page_segment_detail()]
    existing = [p for p, _ in built if (pages_dir / p["name"] / "visuals").exists()]
    if existing and not args.overwrite:
        raise SystemExit(f"pages already authored: {[p['name'] for p in existing]}; pass --overwrite to replace them")

    for page, visuals in built:
        target = pages_dir / page["name"]
        if target.exists():
            shutil.rmtree(target)
        write_json(target / "page.json", page)
        for vis in visuals:
            write_json(target / "visuals" / vis["name"] / "visual.json", vis)
    write_json(pages_dir / "pages.json", {"$schema": SCHEMA + "pagesMetadata/1.1.0/schema.json",
                                         "pageOrder": [p["name"] for p, _ in built],
                                         "activePageName": args.active_page})

    # Theme: Desktop's own Fluent 2 base theme plus the custom theme, registered as Desktop does.
    shared = REPORT / "StaticResources" / "SharedResources" / "BaseThemes" / f"{BASE_THEME}.json"
    shared.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DESKTOP_BASE_THEMES / f"{BASE_THEME}.json", shared)
    registered = REPORT / "StaticResources" / "RegisteredResources" / THEME_FILE
    registered.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(THEME_SRC, registered)
    write_json(REPORT / "definition" / "report.json", {
        "$schema": SCHEMA + "report/3.3.0/schema.json",
        "themeCollection": {
            "baseTheme": {"name": BASE_THEME, "reportVersionAtImport": VERSION_AT_IMPORT, "type": "SharedResources"},
            "customTheme": {"name": THEME_FILE, "reportVersionAtImport": VERSION_AT_IMPORT, "type": "RegisteredResources"},
        },
        "resourcePackages": [
            {"name": "SharedResources", "type": "SharedResources",
             "items": [{"name": BASE_THEME, "path": f"BaseThemes/{BASE_THEME}.json", "type": "BaseTheme"}]},
            {"name": "RegisteredResources", "type": "RegisteredResources",
             "items": [{"name": THEME_FILE, "path": THEME_FILE, "type": "CustomTheme"}]},
        ],
        "settings": {"useStylableVisualContainerHeader": True, "exportDataMode": "AllowSummarized",
                     "defaultDrillFilterOtherVisuals": True, "allowChangeFilterTypes": True,
                     "useEnhancedTooltips": True, "useDefaultAggregateDisplayName": True},
    })
    n = sum(len(v) for _, v in built)
    print(f"wrote {len(built)} pages, {n} visuals, theme {THEME_FILE} on {BASE_THEME}")


if __name__ == "__main__":
    main()
