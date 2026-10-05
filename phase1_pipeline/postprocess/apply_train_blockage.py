from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phase1_pipeline.common import load_config, resolve_config_relative_path, subtract
from phase1_pipeline.raytracing.compute_doppler import unit_vector_from_angles
from phase1_pipeline.raytracing.run_sionna_rt import fallback_trajectory_samples, station_ray_origin
from phase1_pipeline.scenarios import all_base_stations, station_label, station_output_name

Point = Tuple[float, float, float]
Box = Tuple[Point, Point]

BASE_FIELDS = [
    "timestamp_ns",
    "path_id",
    "delay_s",
    "amplitude_real",
    "amplitude_imag",
    "phase_rad",
    "aoa_theta_rad",
    "aoa_phi_rad",
    "aod_theta_rad",
    "aod_phi_rad",
    "doppler_hz",
    "los_flag",
]
EXTRA_FIELDS = ["original_los_flag", "train_blocked", "blockage_loss_db"]


def safe_text(value: object) -> str:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return str(value).encode(encoding, errors="backslashreplace").decode(encoding, errors="replace")


def build_trajectory_by_timestamp(config: Dict) -> Dict[int, Point]:
    return {int(round(time_s * 1e9)): tuple(pos) for time_s, pos in fallback_trajectory_samples(config)}


def train_box_for_rx(config: Dict, rx_pos: Point) -> Box:
    train_cfg = config["train"]
    blockage_cfg = config.get("train_blockage", {})
    length = float(train_cfg.get("length_m", 25.0))
    width = float(train_cfg.get("width_m", 3.4))
    height = float(train_cfg.get("body_height_m", 3.8))
    rx_offset_from_front = float(blockage_cfg.get("rx_offset_from_train_front_m", train_cfg.get("nose_length_m", 4.0)))
    roof_clearance = float(blockage_cfg.get("roof_clearance_m", 0.35))
    lateral_margin = float(blockage_cfg.get("lateral_margin_m", 0.10))
    vertical_margin = float(blockage_cfg.get("vertical_margin_m", 0.05))

    rx_x, rx_y, rx_z = rx_pos
    front_x = rx_x + rx_offset_from_front
    rear_x = front_x - length
    half_width = width / 2.0 + lateral_margin
    top_z = rx_z - roof_clearance + vertical_margin
    bottom_z = top_z - height - vertical_margin
    return (rear_x, rx_y - half_width, bottom_z), (front_x, rx_y + half_width, top_z)


def segment_intersects_box(start: Point, end: Point, box: Box, epsilon: float = 1e-6) -> bool:
    (xmin, ymin, zmin), (xmax, ymax, zmax) = box
    sx, sy, sz = start
    ex, ey, ez = end
    dx, dy, dz = ex - sx, ey - sy, ez - sz
    t_min, t_max = 0.0, 1.0
    for s, d, mn, mx in ((sx, dx, xmin, xmax), (sy, dy, ymin, ymax), (sz, dz, zmin, zmax)):
        if abs(d) < epsilon:
            if s < mn or s > mx:
                return False
            continue
        inv_d = 1.0 / d
        t1 = (mn - s) * inv_d
        t2 = (mx - s) * inv_d
        if t1 > t2:
            t1, t2 = t2, t1
        t_min = max(t_min, t1)
        t_max = min(t_max, t2)
        if t_min > t_max:
            return False
    # Ignore a pure touch exactly at the RX endpoint; the blockage must occur before the antenna.
    return t_min < 1.0 - 1e-4 and t_max > 1e-4


def incoming_segment_from_angles(rx_pos: Point, theta: float, phi: float, lookback_m: float) -> Tuple[Point, Point]:
    arrival_from_source = unit_vector_from_angles(theta, phi)
    propagation_to_receiver = (-arrival_from_source[0], -arrival_from_source[1], -arrival_from_source[2])
    start = (
        rx_pos[0] - propagation_to_receiver[0] * lookback_m,
        rx_pos[1] - propagation_to_receiver[1] * lookback_m,
        rx_pos[2] - propagation_to_receiver[2] * lookback_m,
    )
    return start, rx_pos


def is_path_blocked(row: Dict[str, str], rx_pos: Point, tx_pos: Point, box: Box, lookback_m: float) -> bool:
    if int(row.get("los_flag", "0")) == 1:
        return segment_intersects_box(tx_pos, rx_pos, box)
    theta = float(row["aoa_theta_rad"])
    phi = float(row["aoa_phi_rad"])
    start, end = incoming_segment_from_angles(rx_pos, theta, phi, lookback_m)
    return segment_intersects_box(start, end, box)


def process_station(config: Dict, station: Dict, index: int, trajectory_by_ts: Dict[int, Point]) -> Dict:
    blockage_cfg = config.get("train_blockage", {})
    station_name = station_output_name(station, index)
    input_pattern = str(blockage_cfg.get("input_trace_csv_pattern", "output_unified/{station}.csv"))
    output_pattern = str(blockage_cfg.get("output_trace_csv_pattern", "output_unified_train_blockage/{station}.csv"))
    input_path = resolve_config_relative_path(config, input_pattern.format(station=station_name))
    output_path = resolve_config_relative_path(config, output_pattern.format(station=station_name))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lookback_m = float(blockage_cfg.get("lookback_distance_m", 80.0))
    los_loss_db = float(blockage_cfg.get("los_blockage_loss_db", 22.0))
    nlos_loss_db = float(blockage_cfg.get("nlos_blockage_loss_db", 12.0))
    set_blocked_los_to_nlos = bool(blockage_cfg.get("set_blocked_los_to_nlos", True))
    tx_pos = station_ray_origin(station)

    rows = 0
    blocked_rows = 0
    blocked_los_rows = 0
    timestamps = set()
    blocked_timestamps = set()
    missing_ts = set()

    with input_path.open("r", encoding="utf-8", newline="") as src, output_path.open("w", encoding="utf-8", newline="") as dst:
        reader = csv.DictReader(src)
        fieldnames = list(reader.fieldnames or BASE_FIELDS)
        for extra in EXTRA_FIELDS:
            if extra not in fieldnames:
                fieldnames.append(extra)
        writer = csv.DictWriter(dst, fieldnames=fieldnames)
        writer.writeheader()

        for row in reader:
            rows += 1
            timestamp_ns = int(row["timestamp_ns"])
            timestamps.add(timestamp_ns)
            rx_pos = trajectory_by_ts.get(timestamp_ns)
            if rx_pos is None:
                missing_ts.add(timestamp_ns)
                row["original_los_flag"] = row.get("los_flag", "0")
                row["train_blocked"] = "0"
                row["blockage_loss_db"] = "0.000"
                writer.writerow(row)
                continue

            original_los = int(row.get("los_flag", "0"))
            box = train_box_for_rx(config, rx_pos)
            blocked = is_path_blocked(row, rx_pos, tx_pos, box, lookback_m)
            loss_db = los_loss_db if original_los else nlos_loss_db
            row["original_los_flag"] = str(original_los)
            if blocked:
                blocked_rows += 1
                blocked_timestamps.add(timestamp_ns)
                if original_los:
                    blocked_los_rows += 1
                    if set_blocked_los_to_nlos:
                        row["los_flag"] = "0"
                scale = 10.0 ** (-loss_db / 20.0)
                row["amplitude_real"] = f"{float(row['amplitude_real']) * scale:.17g}"
                row["amplitude_imag"] = f"{float(row['amplitude_imag']) * scale:.17g}"
                row["train_blocked"] = "1"
                row["blockage_loss_db"] = f"{loss_db:.3f}"
            else:
                row["train_blocked"] = "0"
                row["blockage_loss_db"] = "0.000"
            writer.writerow(row)

    return {
        "station": station_label(station, index),
        "output_name": station_name,
        "input_csv": str(input_path),
        "output_csv": str(output_path),
        "rows": rows,
        "timestamps": len(timestamps),
        "blocked_rows": blocked_rows,
        "blocked_row_ratio": round(blocked_rows / rows, 6) if rows else 0.0,
        "blocked_los_rows": blocked_los_rows,
        "blocked_timestamps": len(blocked_timestamps),
        "blocked_timestamp_ratio": round(len(blocked_timestamps) / len(timestamps), 6) if timestamps else 0.0,
        "missing_trajectory_timestamps": len(missing_ts),
    }


def run(config_path: str) -> List[Dict]:
    config = load_config(config_path)
    trajectory_by_ts = build_trajectory_by_timestamp(config)
    summaries = []
    for index, station in enumerate(all_base_stations(config)):
        summary = process_station(config, station, index, trajectory_by_ts)
        summaries.append(summary)
        print(
            f"[{summary['station']}] blocked_rows={summary['blocked_rows']}/{summary['rows']} "
            f"blocked_timestamps={summary['blocked_timestamps']}/{summary['timestamps']} "
            f"output={safe_text(summary['output_csv'])}"
        )

    blockage_cfg = config.get("train_blockage", {})
    manifest_path = resolve_config_relative_path(
        config,
        str(blockage_cfg.get("output_manifest", "output_unified_train_blockage/trace_manifest_train_blockage.json")),
    )
    summary_path = resolve_config_relative_path(
        config,
        str(blockage_cfg.get("summary_json", "output_unified_train_blockage/train_blockage_summary.json")),
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scenario": "with_train_blockage",
        "source_scenario": "no_blockage_sionna_rt",
        "model": {
            "type": "moving_train_blockage_postprocess",
            "rx_offset_from_train_front_m": float(blockage_cfg.get("rx_offset_from_train_front_m", 4.0)),
            "roof_clearance_m": float(blockage_cfg.get("roof_clearance_m", 0.35)),
            "los_blockage_loss_db": float(blockage_cfg.get("los_blockage_loss_db", 22.0)),
            "nlos_blockage_loss_db": float(blockage_cfg.get("nlos_blockage_loss_db", 12.0)),
            "set_blocked_los_to_nlos": bool(blockage_cfg.get("set_blocked_los_to_nlos", True)),
        },
        "stations": summaries,
    }
    with manifest_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    with summary_path.open("w", encoding="utf-8") as handle:
        json.dump(summaries, handle, indent=2, ensure_ascii=False)
    print(f"Manifest: {safe_text(manifest_path)}")
    print(f"Summary: {safe_text(summary_path)}")
    return summaries


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply moving train blockage as a post-processing scenario to Sionna RT CSV traces.")
    parser.add_argument(
        "--config",
        default=str(ROOT / "phase1_pipeline" / "config" / "config.yaml"),
        help="Path to the pipeline YAML configuration file.",
    )
    args = parser.parse_args()
    run(args.config)


if __name__ == "__main__":
    main()
