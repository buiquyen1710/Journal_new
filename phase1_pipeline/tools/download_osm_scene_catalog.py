from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import requests


QUERY_TEMPLATE = """[out:xml][timeout:180];
(
  way[railway]({south},{west},{north},{east});
  way[building]({south},{west},{north},{east});
  way[highway]({south},{west},{north},{east});
  way[natural=water]({south},{west},{north},{east});
  way[waterway]({south},{west},{north},{east});
  way[landuse=forest]({south},{west},{north},{east});
  way[natural=wood]({south},{west},{north},{east});
  way[landuse=grass]({south},{west},{north},{east});
  way[landuse=farmland]({south},{west},{north},{east});
);
(._;>;);
out body;
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--out-dir", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    catalog = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for scene in catalog:
        target = out_dir / f"{scene['id']}.osm"
        if target.exists() and target.stat().st_size > 1000:
            print(scene["id"], "skip existing", target.stat().st_size)
            summary.append({**scene, "osm_file": str(target.resolve()), "bytes": target.stat().st_size})
            continue
        south, west, north, east = scene["bbox"]
        query = QUERY_TEMPLATE.format(south=south, west=west, north=north, east=east)
        response = None
        for attempt in range(4):
            for endpoint in ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"):
                response = requests.get(
                    endpoint,
                    params={"data": query},
                    headers={"User-Agent": "SioNetRail OSM scene catalog"},
                    timeout=240,
                )
                print(scene["id"], endpoint, response.status_code, len(response.text))
                if response.status_code == 200:
                    break
            if response is not None and response.status_code == 200:
                break
            time.sleep(20.0 * (attempt + 1))
        if response is None:
            raise RuntimeError(f"No response for {scene['id']}")
        response.raise_for_status()
        target.write_text(response.text, encoding="utf-8")
        summary.append({**scene, "osm_file": str(target.resolve()), "bytes": target.stat().st_size})
    (out_dir / "download_manifest.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
