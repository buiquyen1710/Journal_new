from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path

import polyscope as ps
from sionna_rt_gui.config import load_config
from sionna_rt_gui.reload import AppHolder


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "phase1_pipeline" / "output_giai_phong_rt_full_sionna_final_physics"
CONFIG = OUT / "sionna_rt_gui_giai_phong.yaml"
META = OUT / "scene_metadata.json"
STATIONS = [
    ("GNB_A", "mpc_gnb_a"),
    ("GNB_B", "mpc_gnb_b"),
    ("GNB_C", "mpc_gnb_c"),
    ("GNB_D", "mpc_gnb_d"),
]


def distance(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((float(a[i]) - float(b[i])) ** 2 for i in range(3)))


def ray_origin(position: list[float], facing: str) -> list[float]:
    x, y, z = [float(v) for v in position]
    face_offset = 0.28 / 2.0 + 0.35
    if facing == "x+":
        x += face_offset
    elif facing == "x-":
        x -= face_offset
    elif facing == "y+":
        y += face_offset
    else:
        y -= face_offset
    return [x, y, z]


def timestamped_rx_samples(metadata: dict) -> list[tuple[int, list[float]]]:
    speed_mps = 350.0 / 3.6
    elapsed_m = 0.0
    previous = None
    samples = []
    for raw in metadata["rx_trajectory_samples"]:
        sample = [float(raw[0]), float(raw[1]), float(raw[2])]
        if previous is not None:
            elapsed_m += distance(sample, previous)
        samples.append((int(round(elapsed_m / speed_mps * 1e9)), sample))
        previous = sample
    return samples


def best_station_snapshot(requested_station: str | None) -> tuple[int, int, int]:
    best = (-1, 0, 0)
    req = requested_station.upper() if requested_station else None
    for idx, (label, output_name) in enumerate(STATIONS):
        if req and req not in {label, output_name.upper(), str(idx)}:
            continue
        csv_path = OUT / f"{output_name}.csv"
        counts: Counter[int] = Counter()
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                counts[int(row["timestamp_ns"])] += 1
        if not counts:
            continue
        timestamp_ns, path_count = counts.most_common(1)[0]
        if path_count > best[0]:
            best = (path_count, timestamp_ns, idx)
    if best[0] < 0:
        raise RuntimeError("No MPC CSV paths were found for the requested station.")
    return best


def main() -> None:
    parser = argparse.ArgumentParser(description="Open SionnaRT GUI for Giai Phong scene with visible ray paths.")
    parser.add_argument("--station", default=None, help="Optional: GNB_A/GNB_B/GNB_C/GNB_D.")
    parser.add_argument("--timestamp-ns", type=int, default=None, help="Optional timestamp_ns from MPC CSV.")
    parser.add_argument("--samples-per-src", type=int, default=5000)
    parser.add_argument("--max-depth", type=int, default=6)
    args = parser.parse_args()

    metadata = json.loads(META.read_text(encoding="utf-8"))
    path_count, best_timestamp_ns, station_idx = best_station_snapshot(args.station)
    timestamp_ns = int(args.timestamp_ns) if args.timestamp_ns is not None else best_timestamp_ns

    rx_samples = timestamped_rx_samples(metadata)
    nearest_timestamp_ns, rx = min(rx_samples, key=lambda item: abs(item[0] - timestamp_ns))

    gnb_positions = metadata["all_gnb_positions_m"]
    gnb_facings = metadata.get("all_gnb_facing") or ["y-"] * len(gnb_positions)
    tx = ray_origin(gnb_positions[station_idx], str(gnb_facings[station_idx]))
    label, output_name = STATIONS[station_idx]

    print(
        f"Opening {label} ({output_name}) at timestamp_ns={nearest_timestamp_ns}, "
        f"rx={rx}, tx={tx}, csv_best_paths={path_count}"
    )

    cfg = load_config(str(CONFIG))
    cfg.paths.auto_update = False
    cfg.radio_map.auto_update = False
    cfg.paths.samples_per_src = int(args.samples_per_src)
    cfg.paths.max_depth = int(args.max_depth)
    cfg.paths.los = True
    cfg.paths.specular_reflection = True
    cfg.paths.diffuse_reflection = True
    cfg.paths.refraction = False
    cfg.paths.diffraction = True

    holder = AppHolder(cfg, scene_filename=None)
    app = holder.app
    app.add_radio_device(tx, is_transmitter=True, allow_auto_update=False)
    app.add_radio_device(rx, is_transmitter=False, allow_auto_update=False)
    try:
        app.scene.get("tx-0").look_at(app.scene.get("rx-0"))
        app.scene.get("rx-0").look_at(app.scene.get("tx-0"))
    except Exception:
        pass
    app.update_paths(show=True)

    mid = [(tx[i] + rx[i]) * 0.5 for i in range(3)]
    camera = (mid[0] - 170.0, mid[1] - 260.0, max(tx[2], rx[2]) + 210.0)
    target = (mid[0], mid[1], max(8.0, (tx[2] + rx[2]) * 0.35))
    ps.look_at(camera, target)
    holder.show()


if __name__ == "__main__":
    main()
