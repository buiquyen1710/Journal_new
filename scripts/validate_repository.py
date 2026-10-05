from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    errors: list[str] = []
    py_files = sorted((ROOT / "phase1_pipeline").rglob("*.py"))
    for path in py_files:
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except Exception as exc:
            errors.append(f"Python syntax: {path.relative_to(ROOT)}: {exc}")

    for rel in (
        "docs/phase0/VERSION_MANIFEST.json",
        "docs/phase0/RUN_MANIFEST_SCHEMA.json",
        "docs/baseline_evidence/baseline_integrity.json",
        "phase1_pipeline/vietnam_railway_osm_scenes/scene_manifest.json",
    ):
        try:
            json.loads((ROOT / rel).read_text(encoding="utf-8-sig"))
        except Exception as exc:
            errors.append(f"JSON: {rel}: {exc}")

    private_path = re.compile(r"(?:[A-Za-z]:\\Users\\|/home/[^/]+/)")
    for path in ROOT.rglob("*"):
        if path == Path(__file__).resolve():
            continue
        if not path.is_file() or ".git" in path.parts or path.suffix.lower() in {".pyc"}:
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            continue
        if private_path.search(text):
            errors.append(f"Private absolute path: {path.relative_to(ROOT)}")

    forbidden = {".blend", ".fbx", ".obj", ".osm", ".csv", ".png", ".log", ".err"}
    for path in ROOT.rglob("*"):
        if path.is_file() and ".git" not in path.parts and path.suffix.lower() in forbidden:
            errors.append(f"Generated/large file committed: {path.relative_to(ROOT)}")

    if errors:
        print("Repository validation FAILED")
        print("\n".join(f"- {item}" for item in errors))
        return 1
    print(f"Repository validation PASSED: {len(py_files)} Python files parsed; JSON, privacy, and asset gates passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
