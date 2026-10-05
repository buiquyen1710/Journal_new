from __future__ import annotations

import argparse
import gzip
import re
import shutil
import urllib.request
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download and unpack one public SRTM HGT tile.")
    parser.add_argument("--tile", required=True, help="SRTM tile name, e.g. N16E108.")
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def latitude_folder(tile: str) -> str:
    if not re.fullmatch(r"[NS]\d{2}[EW]\d{3}", tile):
        raise ValueError(f"Invalid SRTM tile name: {tile}")
    return tile[:3]


def main() -> None:
    args = parse_args()
    tile = args.tile.upper()
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    hgt_path = out_dir / f"{tile}.hgt"
    gz_path = out_dir / f"{tile}.hgt.gz"
    if hgt_path.exists() and hgt_path.stat().st_size > 0:
        print(f"DEM already exists: {hgt_path}")
        return

    url = f"https://s3.amazonaws.com/elevation-tiles-prod/skadi/{latitude_folder(tile)}/{tile}.hgt.gz"
    request = urllib.request.Request(url, headers={"User-Agent": "SioNetRail-DEM/1.0"})
    print(f"Downloading {url}")
    with urllib.request.urlopen(request, timeout=180) as response, gz_path.open("wb") as handle:
        shutil.copyfileobj(response, handle)

    print(f"Unpacking {gz_path}")
    with gzip.open(gz_path, "rb") as source, hgt_path.open("wb") as target:
        shutil.copyfileobj(source, target)
    print(f"Wrote {hgt_path} ({hgt_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
