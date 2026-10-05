from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify immutable large baseline inputs without committing them.")
    parser.add_argument("--source-root", type=Path, required=True, help="Original phase1_pipeline directory")
    args = parser.parse_args()
    lock = json.loads((ROOT / "docs/baseline_evidence/baseline_integrity.json").read_text(encoding="utf-8-sig"))
    failures: list[str] = []
    checked = 0
    for scene, record in lock["scenes"].items():
        directory = args.source_root / record["source_directory_name"]
        for name, expected in record["files"].items():
            path = directory / name
            checked += 1
            if not path.is_file():
                failures.append(f"{scene}/{name}: missing")
                continue
            size = path.stat().st_size
            digest = sha256(path)
            if size != expected["size"] or digest != expected["sha256"]:
                failures.append(f"{scene}/{name}: expected {expected['size']} {expected['sha256']}, got {size} {digest}")
    if failures:
        print(f"Baseline integrity FAILED ({len(failures)}/{checked})")
        print("\n".join(f"- {item}" for item in failures))
        return 1
    print(f"Baseline integrity PASSED: {checked} files across {len(lock['scenes'])} scenes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
