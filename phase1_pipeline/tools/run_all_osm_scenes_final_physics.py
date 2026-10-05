from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


PIPELINE = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PIPELINE.parent
BLENDER_EXE = Path("D:/blender.exe")
CATALOG = PIPELINE / "vietnam_railway_osm_scenes" / "scene_manifest.json"
HAI_VAN_DEM_SCENE_ID = "deo_nui_ven_bien_HaiVanBac-HaiVanNam"
HAI_VAN_DEM_TILE = "N16E108"
OUTPUT_ALIASES = {
    "do_thi_day_dac_GiaiPhong-GiapBat": "output_giai_phong_rt_full_sionna_final_physics",
}


EXPORT_PROFILES = {
    "do_thi_day_dac": {"corridor": 260.0, "area": 6.0},
    "do_thi_cau_song": {"corridor": 220.0, "area": 80.0},
    "dong_bang_cong_nghiep": {"corridor": 320.0, "area": 3.0},
    "do_thi_cang_bien": {"corridor": 340.0, "area": 6.0},
    "dam_pha_ven_bien": {"corridor": 420.0, "area": 2.0},
    "deo_nui_ven_bien": {"corridor": 360.0, "area": 2.0},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run all remaining OSM railway scenes with final-physics SionnaRT.")
    parser.add_argument("--wait-pid", type=int, default=0)
    parser.add_argument("--skip-scene-id", action="append", default=[])
    parser.add_argument("--stall-timeout-min", type=float, default=45.0)
    parser.add_argument("--scene-timeout-hours", type=float, default=8.0)
    return parser.parse_args()


def run(cmd: list[str], cwd: Path, log_path: Path | None = None, timeout_s: float | None = None) -> int:
    print("RUN", " ".join(cmd), flush=True)
    if log_path is None:
        completed = subprocess.run(cmd, cwd=str(cwd), timeout=timeout_s)
        return int(completed.returncode)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        completed = subprocess.run(cmd, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT, timeout=timeout_s)
        return int(completed.returncode)


def process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            process_query_limited_information = 0x1000
            handle = kernel32.OpenProcess(process_query_limited_information, False, int(pid))
            if handle:
                kernel32.CloseHandle(handle)
                return True
            error = kernel32.GetLastError()
            return error == 5
        except Exception:
            powershell = r"C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe"
            completed = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-Command",
                    f"Get-Process -Id {pid} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id",
                ],
                capture_output=True,
                text=True,
            )
            return str(pid) in completed.stdout
    completed = subprocess.run(["ps", "-p", str(pid), "-o", "pid="], capture_output=True, text=True)
    return str(pid) in completed.stdout


def wait_for_pid(pid: int, stall_timeout_min: float) -> None:
    if pid <= 0:
        return
    print(f"Waiting for existing process PID {pid} to finish before starting remaining scenes.", flush=True)
    last_seen = time.time()
    while process_exists(pid):
        time.sleep(60)
        now = time.time()
        if now - last_seen >= stall_timeout_min * 60.0:
            print(f"Still waiting for PID {pid}; elapsed since last report {stall_timeout_min:.1f} min.", flush=True)
            last_seen = now


def base_station_yaml(count: int) -> str:
    blocks = []
    for idx in range(count):
        name = f"GNB_{chr(65 + idx)}"
        out = f"mpc_gnb_{chr(97 + idx)}"
        blocks.append(
            f"  - name: {name}\n"
            f"    output_name: {out}\n"
            f"    position_m: [0.0, 0.0, 30.0]\n"
            f"    facing: y-\n"
            f"    height_m: 30.0\n"
            f"    mast_radius_m: 0.22\n"
            f"    antenna_size_m: [0.9, 0.28, 1.35]\n"
            f"    ray_origin_clearance_m: 0.35"
        )
    return "\n".join(blocks)


def write_config(scene: dict, output_dir_name: str, station_count: int = 6, retry_mode: str = "full") -> Path:
    profile = EXPORT_PROFILES.get(scene["terrain_type"], {"corridor": 320.0, "area": 4.0})
    samples = 2000 if retry_mode == "full" else 1200
    edge = "true" if retry_mode == "full" else "false"
    config_path = PIPELINE / "config" / f"config_{scene['id']}_final_physics.yaml"
    text = f"""scenario:
  type: external_loop_3000m
  name: {scene['id']}_final_physics

external_scene:
  source_blend: {scene['blend_file'].replace(chr(92), '/')}
  trajectory_spacing_m: 25.0
  read_gnb_positions_from_scene: true

export:
  max_obj_file_bytes: 30000000
  skip_curve_objects: true
  keep_curve_keywords: [RT_Rail]
  skip_object_keywords: [RT_Sleeper, RT_Trajectory_Centerline]
  corridor_clip_margin_m: {profile['corridor']}
  skip_object_area_below_m2: {profile['area']}

scene:
  length_m: 0.0
  width_m: 0.0

base_stations:
{base_station_yaml(station_count)}

train:
  receiver_height_m: 4.2
  lateral_offset_m: 0.0
  length_m: 25.0
  width_m: 3.4
  body_height_m: 4.3

simulation:
  frequency_hz: 30000000000.0
  train_speed_kmh: 350.0
  timestep_s: 0.001
  scene_margin_m: 0.0
  duration_s:

ray_tracing:
  max_depth: 6
  max_num_paths: 3000
  samples_per_src: {samples}
  include_train_in_rt_scene: false
  enable_refraction: false
  enable_diffuse_reflection: true
  enable_diffraction: true
  enable_edge_diffraction: {edge}
  enable_diffraction_lit_region: false
  synthetic_array: true
  min_relative_path_gain_db: 110.0
  max_paths_after_filter: 256
  require_sionna_backend: true
  fallback_on_empty_sionna_paths: false
  progress_interval_samples: 5
  skip_snapshot_visualizations: true
  skip_station_validation_plots: true

antenna:
  tx_array:
    num_rows: 8
    num_cols: 4
    vertical_spacing: 0.5
    horizontal_spacing: 0.5
    pattern: tr38901
    polarization: VH
    polarization_model: tr38901_2
  rx_array:
    num_rows: 2
    num_cols: 2
    vertical_spacing: 0.5
    horizontal_spacing: 0.5
    pattern: tr38901
    polarization: VH
    polarization_model: tr38901_2

paths:
  blend_file: {output_dir_name}/Train_{scene['id']}_sionna.blend
  mitsuba_xml: {output_dir_name}/scene.xml
  mesh_dir: {output_dir_name}/meshes
  trace_csv: {output_dir_name}/ns3_trace.csv
  trace_csv_pattern: {output_dir_name}/{{station}}.csv
  trace_manifest: {output_dir_name}/trace_manifest.json
  doppler_plot: {output_dir_name}/doppler_vs_time.png
  doppler_plot_pattern: {output_dir_name}/{{station}}_doppler_vs_time.png
  path_count_plot: {output_dir_name}/path_count_vs_time.png
  path_count_plot_pattern: {output_dir_name}/{{station}}_path_count_vs_time.png
  scene_metadata: {output_dir_name}/scene_metadata.json
"""
    config_path.write_text(text, encoding="utf-8")
    return config_path


def output_dir_name_for(scene_id: str) -> str:
    return OUTPUT_ALIASES.get(scene_id, f"output_{scene_id}_full_sionna_final_physics")


def run_sionna_with_watchdog(config: Path, output_dir: Path, scene_id: str, stall_timeout_min: float, scene_timeout_hours: float) -> bool:
    log_path = output_dir / "sionna_final_physics.log"
    err_path = output_dir / "sionna_final_physics.err"
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    cmd = [
        sys.executable,
        str(PIPELINE / "tools" / "run_sionna_rt_preloaded.py"),
        "--config",
        str(config),
    ]
    with log_path.open("w", encoding="utf-8", errors="replace") as log, err_path.open("w", encoding="utf-8", errors="replace") as err:
        proc = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT), stdout=log, stderr=err, stdin=subprocess.DEVNULL, env=env)
        print(f"{scene_id}: Sionna PID {proc.pid}", flush=True)
        start = time.time()
        last_activity = time.time()
        last_size = -1
        while proc.poll() is None:
            time.sleep(60)
            size = log_path.stat().st_size if log_path.exists() else 0
            newest_csv_mtime = max((p.stat().st_mtime for p in output_dir.glob("mpc_gnb_*.csv")), default=0.0)
            activity = max(log_path.stat().st_mtime if log_path.exists() else 0.0, newest_csv_mtime)
            if size != last_size or activity > last_activity:
                last_activity = max(last_activity, activity)
                last_size = size
            if time.time() - last_activity > stall_timeout_min * 60.0:
                print(f"{scene_id}: watchdog stall after {stall_timeout_min:.1f} min; terminating.", flush=True)
                proc.terminate()
                time.sleep(10)
                if proc.poll() is None:
                    proc.kill()
                return False
            if time.time() - start > scene_timeout_hours * 3600.0:
                print(f"{scene_id}: scene timeout after {scene_timeout_hours:.1f} h; terminating.", flush=True)
                proc.terminate()
                time.sleep(10)
                if proc.poll() is None:
                    proc.kill()
                return False
        print(f"{scene_id}: Sionna exit code {proc.returncode}", flush=True)
        return proc.returncode == 0


def evaluate(output_dir: Path, scene: dict) -> None:
    run(
        [
            sys.executable,
            str(PIPELINE / "tools" / "evaluate_sionna_output_for_ns3.py"),
            "--output-dir",
            str(output_dir),
            "--scene-id",
            scene["id"],
            "--terrain-type",
            scene["terrain_type"],
        ],
        PROJECT_ROOT,
        log_path=output_dir / "evaluate.log",
        timeout_s=600,
    )


def ensure_hai_van_dem(output_dir: Path) -> Path:
    dem_dir = PIPELINE / "dem_sources"
    hgt_path = dem_dir / f"{HAI_VAN_DEM_TILE}.hgt"
    if hgt_path.exists() and hgt_path.stat().st_size > 0:
        return hgt_path
    code = run(
        [
            sys.executable,
            str(PIPELINE / "tools" / "download_srtm_dem_tile.py"),
            "--tile",
            HAI_VAN_DEM_TILE,
            "--output-dir",
            str(dem_dir),
        ],
        PROJECT_ROOT,
        log_path=output_dir / "dem_download.log",
        timeout_s=1800,
    )
    if code != 0 or not hgt_path.exists():
        raise RuntimeError(f"DEM download failed for {HAI_VAN_DEM_TILE}; see {output_dir / 'dem_download.log'}")
    return hgt_path


def add_hai_van_dem(config: Path, scene: dict, output_dir: Path) -> None:
    hgt_path = ensure_hai_van_dem(output_dir)
    bbox = ",".join(str(item) for item in scene["bbox"])
    code = run(
        [
            str(BLENDER_EXE),
            str(output_dir / f"Train_{scene['id']}_sionna.blend"),
            "--background",
            "--python",
            str(PIPELINE / "blender" / "add_srtm_dem_to_scene.py"),
            "--",
            "--config",
            str(config),
            "--scene-id",
            scene["id"],
            "--bbox",
            bbox,
            "--hgt",
            str(hgt_path),
            "--grid",
            "180",
        ],
        PROJECT_ROOT,
        log_path=output_dir / "dem_prepare.log",
        timeout_s=3600,
    )
    if code != 0:
        raise RuntimeError(f"DEM prepare failed for {scene['id']}; see {output_dir / 'dem_prepare.log'}")


def run_scene(scene: dict, stall_timeout_min: float, scene_timeout_hours: float) -> None:
    output_dir_name = output_dir_name_for(scene["id"])
    output_dir = PIPELINE / output_dir_name
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "batch_error.txt").unlink(missing_ok=True)
    config = write_config(scene, output_dir_name, station_count=6, retry_mode="full")
    prepare_code = run(
        [
            str(BLENDER_EXE),
            scene["blend_file"],
            "--background",
            "--python",
            str(PIPELINE / "blender" / "prepare_osm_rail_scene_for_sionna.py"),
            "--",
            "--config",
            str(config),
            "--scene-id",
            scene["id"],
            "--terrain-type",
            scene["terrain_type"],
        ],
        PROJECT_ROOT,
        log_path=output_dir / "prepare.log",
        timeout_s=3600,
    )
    if prepare_code != 0:
        raise RuntimeError(f"Blender prepare failed for {scene['id']} with exit code {prepare_code}; see {output_dir / 'prepare.log'}")
    if scene["id"] == HAI_VAN_DEM_SCENE_ID:
        add_hai_van_dem(config, scene, output_dir)
    metadata = json.loads((output_dir / "scene_metadata.json").read_text(encoding="utf-8"))
    station_count = len(metadata.get("all_gnb_positions_m", []))
    config = write_config(scene, output_dir_name, station_count=station_count, retry_mode="full")
    export_code = run(
        [
            str(BLENDER_EXE),
            str(output_dir / f"Train_{scene['id']}_sionna.blend"),
            "--background",
            "--python",
            str(PIPELINE / "export" / "export_mitsuba.py"),
            "--",
            "--config",
            str(config),
        ],
        PROJECT_ROOT,
        log_path=output_dir / "export.log",
        timeout_s=3600,
    )
    if export_code != 0:
        raise RuntimeError(f"Blender export failed for {scene['id']} with exit code {export_code}; see {output_dir / 'export.log'}")
    ok = run_sionna_with_watchdog(config, output_dir, scene["id"], stall_timeout_min, scene_timeout_hours)
    if not ok:
        print(f"{scene['id']}: retrying with edge diffraction disabled and fewer samples.", flush=True)
        config = write_config(scene, output_dir_name, station_count=station_count, retry_mode="retry")
        ok = run_sionna_with_watchdog(config, output_dir, scene["id"], stall_timeout_min, scene_timeout_hours)
    evaluate(output_dir, scene)


def aggregate(scene_ids: list[str]) -> None:
    rows = []
    for scene_id in scene_ids:
        output_dir = PIPELINE / output_dir_name_for(scene_id)
        eval_path = output_dir / "technical_ns3_evaluation.json"
        if not eval_path.exists():
            continue
        rows.append(json.loads(eval_path.read_text(encoding="utf-8")))
    out_json = PIPELINE / "output_all_scenes_final_physics_summary.json"
    out_md = PIPELINE / "output_all_scenes_final_physics_summary.md"
    out_json.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    lines = ["# All Scenes Final Physics Summary", ""]
    lines.append("| Scene | Terrain | Status | Track m | RX | gNB | Key issues |")
    lines.append("|---|---|---:|---:|---:|---:|---|")
    for row in rows:
        issues = "; ".join(row.get("issues", [])) or "none"
        lines.append(
            f"| {row['scene_id']} | {row.get('terrain_type','')} | {row.get('status','')} | "
            f"{float(row.get('track_length_m') or 0):.1f} | {row.get('rx_samples',0)} | {len(row.get('gnb_positions_m', []))} | {issues} |"
        )
    out_md.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    wait_for_pid(args.wait_pid, args.stall_timeout_min)
    scenes = json.loads(CATALOG.read_text(encoding="utf-8"))
    skipped = set(args.skip_scene_id)
    for scene in scenes:
        if scene["id"] in skipped:
            output_dir = PIPELINE / output_dir_name_for(scene["id"])
            if output_dir.exists() and (output_dir / "trace_manifest.json").exists():
                print(f"Evaluating pre-existing skipped scene {scene['id']}", flush=True)
                evaluate(output_dir, scene)
    selected = [scene for scene in scenes if scene["id"] not in set(args.skip_scene_id)]
    all_ids = [scene["id"] for scene in scenes]
    for scene in selected:
        print(f"=== Running {scene['id']} ===", flush=True)
        try:
            run_scene(scene, args.stall_timeout_min, args.scene_timeout_hours)
        except Exception as exc:
            output_dir = PIPELINE / f"output_{scene['id']}_full_sionna_final_physics"
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "batch_error.txt").write_text(str(exc), encoding="utf-8")
            print(f"{scene['id']}: ERROR {exc}", flush=True)
    aggregate(all_ids)
    print("Batch complete.", flush=True)


if __name__ == "__main__":
    main()
