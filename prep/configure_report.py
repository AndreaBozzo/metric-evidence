"""Point the Power BI project at this clone's data folder.

Power Query cannot resolve paths relative to the .pbip, so the DataFolder
parameter must hold an absolute path. The repository ships a placeholder; run
this once after cloning (or after moving the folder). It rewrites the one
parameter line in the TMDL and changes nothing else.

Usage:
  uv run python prep/configure_report.py              # use ./data (or --data-dir / METRIC_EVIDENCE_DATA_DIR)
  uv run python prep/configure_report.py --reset      # restore the placeholder
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from paths import REPO_ROOT, data_dir_from_args

EXPRESSIONS = REPO_ROOT / "powerbi" / "MetricEvidence.SemanticModel" / "definition" / "expressions.tmdl"
PLACEHOLDER = "<not set: run prep/configure_report.py>"
LINE = re.compile(r'^(expression DataFolder = ")((?:[^"]|"")*)(" meta )', re.MULTILINE)


def set_data_folder(value: str, expressions: Path = EXPRESSIONS) -> tuple[str, str]:
    """Rewrite the DataFolder parameter value; returns (old, new)."""
    text = expressions.read_text(encoding="utf-8")
    matches = LINE.findall(text)
    if len(matches) != 1:
        raise SystemExit(f"expected one DataFolder parameter in {expressions}, found {len(matches)}")
    old = matches[0][1].replace('""', '"')
    escaped = value.replace('"', '""')  # M string literal escaping
    expressions.write_text(LINE.sub(lambda m: m.group(1) + escaped + m.group(3), text), encoding="utf-8")
    return old, value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="restore the placeholder value")
    data = data_dir_from_args(parser)
    if parser.parse_args().reset:
        value = PLACEHOLDER
    else:
        if not (data / "orders.csv").exists():
            sys.exit(f"{data} has no orders.csv; generate the data first (see README)")
        value = str(data.resolve()) + "\\"
    old, new = set_data_folder(value)
    print(f"DataFolder: {old}\n         -> {new}")
    if old != new:
        print("If the report is open in Power BI Desktop, close and reopen it, then Refresh.")


if __name__ == "__main__":
    main()
