"""The one place the local data folder is resolved.

Order of precedence: --data-dir, then METRIC_EVIDENCE_DATA_DIR, then ./data
next to this repository. Power BI reads the same folder through its DataFolder
parameter.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def default_data_dir() -> Path:
    env = os.environ.get("METRIC_EVIDENCE_DATA_DIR")
    return Path(env) if env else REPO_ROOT / "data"


def data_dir_from_args(parser: argparse.ArgumentParser) -> Path:
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    out: Path = parser.parse_args().data_dir
    out.mkdir(parents=True, exist_ok=True)
    return out
