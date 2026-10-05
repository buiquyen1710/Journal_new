from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path

import polyscope as ps
from sionna_rt_gui.config import load_config as load_gui_config
from sionna_rt_gui.reload import AppHolder


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phase1_pipeline.common import load_config, resolve_output_paths
from phase1_pipeline.raytracing.run_sionna_rt import external_loop_base_stations, fallback_trajectory_samples, station_ray_origin
from phase1_pipeline.scenarios import all_base_stations, is_external_loop_scenario, station_label, station_output_name


def count_paths(csv_path: Path) -> Counter[int]:
    counts: Counter[int] = Counter()
    if not csv_path.exists():
        return counts
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                counts[int(float(row["timestamp_ns"]))] += 1
            except Exception:
                pass
    return counts


def write_gui_config(scene_xml: Path, out_dir: Path) -> Path:
    gui_path = out_dir / "sionna_rt_gui_auto_paths.yaml"
    gui_path.write_text(
        "\n".join(
            [
                f"scene_filename: {scene_xml.as_posix()}",
                "background_color: [0.02, 0.02, 0.02]",
                "gui_mode: FULL",
                "show_help_window: true",
                "create_example_scenario: false",
                "radio_material_thickness: 0.3",
                "radio_material_scattering_coefficient: 0.2",
                "rendering:",
                "  mode: RASTERIZATION",
                "  relative_resolution: 0.75",
                "  spp_per_frame: 2",
                "  max_accumulated_spp: 16",
                "  envmap_factor: 0.15",
                "  default_slice_plane_enabled: false",
                "radio_map:",
                "  auto_update: false",
                "paths:",
                "  auto_update: false",
                "  max_depth: 4",
                "  max_num_paths_per_src: 3000",
                "  samples_per_src: 1000",
                "  synthetic_array: true",
                "  los: true",
                "  specular_reflection: true",
                "  diffuse_reflection: true",
                "  refraction: true",
                "  diffraction: true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return gui_path


def stations_for_config(config: dict) -> list[dict]:
    if is_external_loop_scenario(config):
        return external_loop_base_stations(config)
    return list(all_base_stations(config))


def choose_best(config: dict, stations: list[dict], requested_station: str | None):
    output_paths = resolve_output_paths(config)
    out_dir = output_paths["mitsuba_xml"].parent
    req = requested_station.upper() if requested_station else None
    best = (-1, 0, 0)
    for idx, station in enumerate(stations):
        label = station_label(station, idx).upper()
        output_name = station_output_name(station, idx)
        if req and req not in {label, output_name.upper(), str(idx)}:
            continue
        counts = count_paths(out_dir / f"{output_name}.csv")
        if not counts:
            continue
        timestamp_ns, path_count = counts.most_common(1)[0]
        if path_count > best[0]:
            best = (path_count, timestamp_ns, idx)
    if best[0] < 0:
        idx = 0
        return idx, stations[idx], 0, 0
    path_count, timestamp_ns, idx = best
    return idx, stations[idx], int(timestamp_ns), int(path_count)


def camera(tx: list[float], rx: list[float]):
    mid = [(tx[i] + rx[i]) * 0.5 for i in range(3)]
    dx = rx[0] - tx[0]
    dy = rx[1] - tx[1]
    span = max(math.sqrt(dx * dx + dy * dy), 240.0)
    pos = (mid[0] - 0.65 * span, mid[1] - 0.95 * span, max(tx[2], rx[2]) + 0.75 * span)
    target = (mid[0], mid[1], max(8.0, (tx[2] + rx[2]) * 0.35))
    return pos, target


def parse_vec3(text: str) -> tuple[float, float, float]:
    parts = [float(item.strip()) for item in text.split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("Expected three comma-separated values: x,y,z")
    return (parts[0], parts[1], parts[2])


def main() -> None:
    parser = argparse.ArgumentParser(description="Open SionnaRT GUI with one TX/RX pair and computed paths.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--scene-xml", default=None, help="Optional visualization XML override.")
    parser.add_argument("--station", default=None, help="Optional station label/output/index.")
    parser.add_argument("--timestamp-ns", type=int, default=None)
    parser.add_argument("--samples-per-src", type=int, default=1000)
    parser.add_argument("--max-depth", type=int, default=4)
    parser.add_argument("--no-diffuse", action="store_true")
    parser.add_argument("--no-diffraction", action="store_true")
    parser.add_argument("--camera-eye", type=parse_vec3, default=None, help="Manual camera eye: x,y,z")
    parser.add_argument("--camera-target", type=parse_vec3, default=None, help="Manual camera target: x,y,z")
    parser.add_argument("--device-radius-m", type=float, default=None, help="Absolute TX/RX marker radius in meters.")
    parser.add_argument("--path-radius-m", type=float, default=None, help="Absolute ray path line radius in meters.")
    args = parser.parse_args()

    config = load_config(args.config)
    output_paths = resolve_output_paths(config)
    scene_xml = Path(args.scene_xml) if args.scene_xml else output_paths["mitsuba_xml"]
    stations = stations_for_config(config)
    station_idx, station, best_timestamp_ns, csv_count = choose_best(config, stations, args.station)
    timestamp_ns = int(args.timestamp_ns) if args.timestamp_ns is not None else best_timestamp_ns
    samples = fallback_trajectory_samples(config)
    if timestamp_ns:
        target_s = timestamp_ns / 1e9
        time_s, rx_pos_tuple = min(samples, key=lambda item: abs(float(item[0]) - target_s))
    else:
        time_s, rx_pos_tuple = samples[len(samples) // 2]
        timestamp_ns = int(round(float(time_s) * 1e9))
    rx = [float(x) for x in rx_pos_tuple]
    tx = [float(x) for x in station_ray_origin(station)]

    gui_config_path = write_gui_config(scene_xml, output_paths["mitsuba_xml"].parent)
    cfg = load_gui_config(str(gui_config_path))
    cfg.paths.auto_update = False
    cfg.radio_map.auto_update = False
    cfg.paths.samples_per_src = int(args.samples_per_src)
    cfg.paths.max_depth = int(args.max_depth)
    cfg.paths.los = True
    cfg.paths.specular_reflection = True
    cfg.paths.diffuse_reflection = not bool(args.no_diffuse)
    cfg.paths.refraction = True
    cfg.paths.diffraction = not bool(args.no_diffraction)

    print(
        f"Opening {config.get('scenario', {}).get('name', Path(args.config).stem)} | "
        f"{station_label(station, station_idx)} / {station_output_name(station, station_idx)} | "
        f"timestamp_ns={timestamp_ns} | csv_paths={csv_count} | tx={tx} | rx={rx}",
        flush=True,
    )

    holder = AppHolder(cfg, scene_filename=None)
    app = holder.app
    app.add_radio_device(tx, is_transmitter=True, allow_auto_update=False)
    app.add_radio_device(rx, is_transmitter=False, allow_auto_update=False)
    if args.device_radius_m is not None:
        for cloud_name in ("Transmitters", "Receivers"):
            if ps.has_point_cloud(cloud_name):
                ps.get_point_cloud(cloud_name).set_radius(float(args.device_radius_m), relative=False)
    try:
        app.scene.get("tx-0").look_at(app.scene.get("rx-0"))
        app.scene.get("rx-0").look_at(app.scene.get("tx-0"))
    except Exception:
        pass
    app.update_paths(show=True)
    if args.path_radius_m is not None and ps.has_curve_network("paths"):
        ps.get_curve_network("paths").set_radius(float(args.path_radius_m), relative=False)
    eye, target = camera(tx, rx)
    if args.camera_eye is not None:
        eye = args.camera_eye
    if args.camera_target is not None:
        target = args.camera_target
    ps.look_at(eye, target)
    holder.show()


if __name__ == "__main__":
    main()
