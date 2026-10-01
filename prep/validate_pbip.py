"""Validate every PBIP/PBIR JSON file against the schema named in its $schema.

Schemas are fetched from github.com/microsoft/json-schemas (the source of
developer.microsoft.com/json-schemas) and cached in .cache/schemas. Passing
this check means the files are well-formed; it does not mean Desktop renders
them, which still has to be confirmed by opening the project.

Usage: uv run python prep/validate_pbip.py [path ...]   (default: powerbi/)
"""

from __future__ import annotations

import json
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


def validate(path: Path, registry: Registry) -> list[str]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    url = doc.get("$schema")
    if not url:
        return [f"{path}: no $schema"]
    schema = fetch(url)
    schema.setdefault("$id", url)
    validator = Draft7Validator(schema, registry=registry)
    return [
        f"{path}: {'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message[:300]}"
        for e in sorted(validator.iter_errors(doc), key=lambda e: list(map(str, e.absolute_path)))
    ]


def main() -> int:
    roots = [Path(p) for p in sys.argv[1:]] or [REPO_ROOT / "powerbi"]
    # SharedResources holds Desktop's own base theme, copied verbatim; .pbi holds local state.
    files = [p for r in roots for p in sorted(r.rglob("*.json"))
             if ".pbi" not in p.parts and "SharedResources" not in p.parts]
    files += [p for r in roots for p in sorted(r.rglob("*.pbir")) + sorted(r.rglob("*.pbism"))
              + sorted(r.rglob("*.pbip"))]
    registry = Registry(retrieve=retrieve)
    errors = []
    for f in files:
        errors += validate(f, registry)
    for e in errors:
        print(e)
    print(f"{len(files)} files checked, {len(errors)} schema errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
