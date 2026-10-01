"""Validate every PBIP/PBIR JSON file against the schema named in its $schema.

Schemas are fetched from github.com/microsoft/json-schemas (the source of
developer.microsoft.com/json-schemas) and cached in .cache/schemas. Passing
this check means the files are well-formed; it does not mean Desktop renders
them, which still has to be confirmed by opening the project.

Usage: uv run python prep/validate_pbip.py [path ...]   (default: powerbi/)
"""

from __future__ import annotations

import json
import re
import urllib.error
import sys
import urllib.request
from pathlib import Path

from jsonschema import Draft7Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

from paths import REPO_ROOT

PREFIX = "https://developer.microsoft.com/json-schemas/"
RAW = "https://raw.githubusercontent.com/microsoft/json-schemas/main/"
# Report themes declare the theme schema published in powerbi-desktop-samples.
THEME_PREFIX = "https://raw.githubusercontent.com/microsoft/powerbi-desktop-samples/"
CACHE = REPO_ROOT / ".cache" / "schemas" / "by-url"


def fetch(url: str) -> dict:
    if url.startswith(PREFIX):
        rel, source = url[len(PREFIX):], RAW + url[len(PREFIX):]
    elif url.startswith(THEME_PREFIX):
        rel, source = "themes/" + url.rsplit("/", 1)[-1].replace("%20", " "), url
    else:
        raise ValueError(f"unexpected schema host: {url}")
    local = CACHE / rel
    if not local.exists():
        local.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(source, timeout=60) as resp:
            local.write_bytes(resp.read())
    return json.loads(local.read_text(encoding="utf-8"))


def retrieve(uri: str) -> Resource:
    return Resource.from_contents(fetch(uri), default_specification=DRAFT7)


def fetch_published(url: str) -> tuple[str, dict]:
    """The declared schema, or the newest published minor version of the same major.

    Desktop can write schema versions before Microsoft publishes them (e.g.
    visualContainer 2.13.0 in Desktop 2.158). Falling back is reported, never silent.
    """
    try:
        return url, fetch(url)
    except urllib.error.HTTPError as e:
        m = re.search(r"/(\d+)\.(\d+)\.(\d+)/schema\.json$", url)
        if e.code != 404 or not m:
            raise
        major, minor = int(m.group(1)), int(m.group(2))
        for older in range(minor - 1, -1, -1):
            candidate = url[: m.start()] + f"/{major}.{older}.0/schema.json"
            try:
                return candidate, fetch(candidate)
            except urllib.error.HTTPError:
                continue
        raise


NOTES: list[str] = []


def validate(path: Path, registry: Registry) -> list[str]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    url = doc.get("$schema")
    if not url:
        return [f"{path}: no $schema"]
    used, schema = fetch_published(url)
    if used != url:
        shown = path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path
        NOTES.append(f"{shown}: {url.rsplit('/', 3)[-3]} {url.rsplit('/', 2)[-2]} "
                     f"is not published yet; validated against {used.rsplit('/', 2)[-2]}")
    schema.setdefault("$id", used)
    validator = Draft7Validator(schema, registry=registry)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(map(str, e.absolute_path)))
    if used != url:
        # The older schema pins its own URL in "$schema"; that one mismatch is expected.
        errors = [e for e in errors if list(e.absolute_path) != ["$schema"]]
    return [f"{path}: {'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message[:300]}" for e in errors]


def main() -> int:
    roots = [Path(p) for p in sys.argv[1:]] or [REPO_ROOT / "powerbi"]
    # SharedResources holds Desktop's own base theme, copied verbatim; .pbi holds local state.
    files = [p for r in roots for p in sorted(r.rglob("*.json"))
             if ".pbi" not in p.parts and "SharedResources" not in p.parts]
    files += [p for r in roots for p in sorted(r.rglob("*.pbir")) + sorted(r.rglob("*.pbism"))
              + sorted(r.rglob("*.pbip")) + sorted(r.rglob(".platform"))]
    registry = Registry(retrieve=retrieve)
    errors = []
    for f in files:
        errors += validate(f, registry)
    for e in errors:
        print(e)
    for n in NOTES:
        print("note:", n)
    print(f"{len(files)} files checked, {len(errors)} schema errors"
          + (f", {len(NOTES)} validated against an older published schema version" if NOTES else ""))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
