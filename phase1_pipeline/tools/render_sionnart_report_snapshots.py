from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phase1_pipeline.common import load_config, resolve_output_paths
from phase1_pipeline.raytracing.run_sionna_rt import (
    build_planar_array,
    external_loop_base_stations,
    fallback_trajectory_samples,
    prepare_ascii_safe_scene,
    station_ray_origin,
    try_import_sionna,
)
from phase1_pipeline.scenarios import all_base_stations, is_external_loop_scenario, station_label, station_output_name


DEFAULT_CONFIGS = [
    ROOT / "phase1_pipeline" / "config" / "config_giai_phong_rt_full_sionna_final_physics.yaml",
    ROOT / "phase1_pipeline" / "config" / "config_do_thi_cau_song_LongBien-GiaLam_final_physics.yaml",
    ROOT / "phase1_pipeline" / "config" / "config_dong_bang_cong_nghiep_HaiDuong-PhuThai_final_physics.yaml",
    ROOT / "phase1_pipeline" / "config" / "config_do_thi_cang_bien_HaiPhong-ThuongLy_final_physics.yaml",
    ROOT / "phase1_pipeline" / "config" / "config_dam_pha_ven_bien_LangCo-HaiVanBac_final_physics.yaml",
    ROOT / "phase1_pipeline" / "config" / "config_deo_nui_ven_bien_HaiVanBac-HaiVanNam_final_physics.yaml",
]


def slug(text: str) -> str:
    out = []
    for ch in text:
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "_":
            out.append("_")
    return "".join(out).strip("_").lower()


def stations_for_config(config: Dict) -> List[Dict]:
    if is_external_loop_scenario(config):
        return external_loop_base_stations(config)
    return list(all_base_stations(config))


def count_csv_paths(csv_path: Path) -> Counter[int]:
    counts: Counter[int] = Counter()
    if not csv_path.exists():
        return counts
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                counts[int(float(row["timestamp_ns"]))]
            except Exception:
                continue
            counts[int(float(row["timestamp_ns"]))] += 1
    return counts


def choose_snapshot(config: Dict, stations: List[Dict]) -> Tuple[int, Dict, int, int]:
    output_paths = resolve_output_paths(config)
    out_dir = output_paths["mitsuba_xml"].parent
    best = (-1, 0, 0)
    for idx, station in enumerate(stations):
        output_name = station_output_name(station, idx)
        counts = count_csv_paths(out_dir / f"{output_name}.csv")
        if not counts:
            continue
        timestamp_ns, path_count = counts.most_common(1)[0]
        if path_count > best[0]:
            best = (path_count, timestamp_ns, idx)
    if best[0] < 0:
        mid_idx = max(0, len(stations) // 2)
        return mid_idx, stations[mid_idx], 0, 0
    path_count, timestamp_ns, station_idx = best
    return station_idx, stations[station_idx], timestamp_ns, path_count


def closest_sample(samples: Iterable[Tuple[float, Tuple[float, float, float]]], timestamp_ns: int):
    target_s = timestamp_ns / 1e9
    return min(samples, key=lambda item: abs(float(item[0]) - target_s))


def camera_for_paths(Camera, mi, tx_pos, rx_pos, view: str):
    mid = [(float(tx_pos[i]) + float(rx_pos[i])) * 0.5 for i in range(3)]
    dx = float(rx_pos[0]) - float(tx_pos[0])
    dy = float(rx_pos[1]) - float(tx_pos[1])
    horizontal = max(math.sqrt(dx * dx + dy * dy), 250.0 if view == "overview" else 90.0)
    if view == "close":
        position = (
            float(rx_pos[0]) - 0.30 * dx - 0.28 * horizontal,
            float(rx_pos[1]) - 0.30 * dy - 0.38 * horizontal,
            max(float(tx_pos[2]), float(rx_pos[2])) + 0.42 * horizontal,
        )
        look_at = (float(rx_pos[0]), float(rx_pos[1]), float(rx_pos[2]) + 3.0)
        fov = 52.0
    else:
        position = (
            mid[0] - 0.55 * horizontal,
            mid[1] - 0.85 * horizontal,
            max(float(tx_pos[2]), float(rx_pos[2])) + 0.70 * horizontal,
        )
        look_at = (mid[0], mid[1], max(8.0, (float(tx_pos[2]) + float(rx_pos[2])) * 0.35))
        fov = 58.0
    return Camera(position=mi.Point3f(*position), look_at=mi.Point3f(*look_at)), fov


def render_config(config_path: Path, output_dir: Path, args) -> Dict:
    imports = try_import_sionna()
    if imports is None:
        raise RuntimeError("Sionna RT is not available in this Python environment.")
    mi = imports["mi"]
    load_scene = imports["load_scene"]
    Transmitter = imports["Transmitter"]
    Receiver = imports["Receiver"]
    PathSolver = imports["PathSolver"]
    Camera = __import__("sionna.rt", fromlist=["Camera"]).Camera

    config = load_config(config_path)
    output_paths = resolve_output_paths(config)
    scenario_name = str(config.get("scenario", {}).get("name", config_path.stem))
    stations = stations_for_config(config)
    samples = fallback_trajectory_samples(config)
    station_idx, station, timestamp_ns, csv_path_count = choose_snapshot(config, stations)
    if timestamp_ns:
        time_s, rx_pos = closest_sample(samples, timestamp_ns)
    else:
        time_s, rx_pos = samples[len(samples) // 2]
        timestamp_ns = int(round(float(time_s) * 1e9))
    tx_pos = station_ray_origin(station)

    scene_path = prepare_ascii_safe_scene(output_paths)
    scene = load_scene(str(scene_path), merge_shapes=False)
    scene.frequency = float(config["simulation"]["frequency_hz"])
    scene.tx_array = build_planar_array(config, imports, "tx_array")
    scene.rx_array = build_planar_array(config, imports, "rx_array")

    tx = Transmitter(name="tx", position=mi.Point3f(*tx_pos), orientation=mi.Point3f(0.0, 0.0, 0.0))
    rx = Receiver(name="rx", position=mi.Point3f(*rx_pos), orientation=mi.Point3f(0.0, 0.0, 0.0))
    scene.add(tx)
    scene.add(rx)
    tx.look_at(rx)
    rx.look_at(tx)

    solver = PathSolver()
    paths = solver(
        scene=scene,
        max_depth=int(args.max_depth),
        max_num_paths_per_src=int(args.max_num_paths),
        samples_per_src=int(args.samples_per_src),
        synthetic_array=bool(config["ray_tracing"].get("synthetic_array", True)),
        los=True,
        specular_reflection=True,
        diffuse_reflection=bool(args.diffuse),
        refraction=False,
        diffraction=bool(args.diffraction),
        edge_diffraction=bool(args.diffraction),
        diffraction_lit_region=False,
        seed=int(args.seed),
    )

    scene_slug = slug(scenario_name)
    image_path = output_dir / f"{scene_slug}_sionnart_snapshot.png"
    camera, fov = camera_for_paths(Camera, mi, tx_pos, rx_pos, args.view)
    scene.render_to_file(
        camera=camera,
        filename=str(image_path),
        paths=paths,
        resolution=(int(args.width), int(args.height)),
        num_samples=int(args.render_samples),
        fov=float(fov),
        show_devices=bool(args.show_devices),
        show_orientations=False,
        lighting_scale=float(args.lighting_scale),
    )

    valid_paths = None
    try:
        valid_paths = int(paths.valid.numpy().sum())
    except Exception:
        pass

    return {
        "scenario": scenario_name,
        "config": str(config_path),
        "scene_xml": str(output_paths["mitsuba_xml"]),
        "image": str(image_path),
        "station": station_label(station, station_idx),
        "station_output": station_output_name(station, station_idx),
        "timestamp_ns": int(timestamp_ns),
        "time_s": float(time_s),
        "rx_position_m": [float(x) for x in rx_pos],
        "tx_position_m": [float(x) for x in tx_pos],
        "csv_path_count_at_selected_timestamp": int(csv_path_count),
        "sionna_valid_paths_raw": valid_paths,
        "samples_per_src": int(args.samples_per_src),
        "max_depth": int(args.max_depth),
        "diffuse": bool(args.diffuse),
        "diffraction": bool(args.diffraction),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Render one SionnaRT GUI-style ray snapshot per final physics scene.")
    parser.add_argument("--output-dir", default=str(ROOT / "phase1_pipeline" / "report_sionnart_gui_snapshots"))
    parser.add_argument("--configs", nargs="*", default=[str(p) for p in DEFAULT_CONFIGS])
    parser.add_argument("--samples-per-src", type=int, default=3000)
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--max-num-paths", type=int, default=3000)
    parser.add_argument("--render-samples", type=int, default=48)
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=1000)
    parser.add_argument("--lighting-scale", type=float, default=1.0)
    parser.add_argument("--view", choices=["overview", "close"], default="overview")
    parser.add_argument("--show-devices", action="store_true")
    parser.add_argument("--diffuse", action="store_true", default=True)
    parser.add_argument("--no-diffuse", action="store_false", dest="diffuse")
    parser.add_argument("--diffraction", action="store_true", default=True)
    parser.add_argument("--no-diffraction", action="store_false", dest="diffraction")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for cfg_text in args.configs:
        config_path = Path(cfg_text)
        if not config_path.exists():
            print(f"SKIP missing config: {config_path}")
            continue
        print(f"Rendering {config_path.name} ...", flush=True)
        manifest.append(render_config(config_path, output_dir, args))
        print(f"  -> {manifest[-1]['image']}", flush=True)
    manifest_path = output_dir / "sionnart_report_snapshot_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
