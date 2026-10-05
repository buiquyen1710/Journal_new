from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
from collections import defaultdict
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create ns-3 ready copies of Sionna CSV traces with geometry-based LOS labels.")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--metadata", required=True)
    return parser.parse_args()


def timestamp_zones(metadata_path: Path) -> dict[int, tuple[float, str]]:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    speed = 350.0 / 3.6
    zones = {}
    distance = 0.0
    prev = None
    for point in metadata["rx_trajectory_samples"]:
        p = tuple(float(v) for v in point[:3])
        if prev is not None:
            distance += math.dist(prev, p)
        prev = p
        timestamp_ns = int(round((distance / speed) * 1e9))
        if distance < 750.0:
            zone = "A"
        elif distance < 1500.0:
            zone = "B"
        elif distance < 2000.0:
            zone = "C_tunnel"
        elif distance < 3000.0:
            zone = "D"
        else:
            zone = "Return"
        zones[timestamp_ns] = (distance, zone)
    return zones


def corrected_los_flag(station_name: str, distance_m: float, zone: str, current_flag: str) -> str:
    if zone != "C_tunnel":
        return current_flag
    if station_name == "mpc_gnb_c":
        # Portal gNB keeps LOS for the first ~150 m into the tunnel, then tunnel curvature/overburden dominates.
        return "1" if distance_m <= 1650.0 else "0"
    return "0"


def process_csv(input_csv: Path, output_csv: Path, zones: dict[int, tuple[float, str]]) -> dict:
    station = input_csv.stem
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    changed = 0
    by_zone = defaultdict(int)
    with input_csv.open(newline="", encoding="utf-8") as src, output_csv.open("w", newline="", encoding="utf-8") as dst:
        reader = csv.DictReader(src)
        writer = csv.DictWriter(dst, fieldnames=reader.fieldnames)
        writer.writeheader()
        for row in reader:
            timestamp = int(row["timestamp_ns"])
            distance, zone = zones.get(timestamp, (0.0, "unknown"))
            old = row["los_flag"]
            row["los_flag"] = corrected_los_flag(station, distance, zone, old)
            changed += int(row["los_flag"] != old)
            by_zone[zone] += 1
            total += 1
            writer.writerow(row)
    return {"station": station, "rows": total, "los_flags_changed": changed, "rows_by_zone": dict(by_zone)}


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    zones = timestamp_zones(Path(args.metadata))
    summaries = []
    for csv_path in sorted(input_dir.glob("mpc_gnb_*.csv")):
        summaries.append(process_csv(csv_path, output_dir / csv_path.name, zones))
    for name in ("scene_metadata.json", "trace_manifest.json", "scale_report.md", "path_count_vs_time.png", "doppler_vs_time.png"):
        src = input_dir / name
        if src.exists():
            shutil.copy2(src, output_dir / name)
    (output_dir / "ns3_ready_manifest.json").write_text(
        json.dumps(
            {
                "source_output_dir": str(input_dir.resolve()),
                "los_policy": "Geometry-based tunnel LOS correction. Non-portal gNBs are NLOS in Zone C; GNB_C keeps LOS only for s<=1650m.",
                "summaries": summaries,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
