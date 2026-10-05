from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


PIPELINE = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PIPELINE.parent
CATALOG = PIPELINE / "vietnam_railway_osm_scenes" / "scene_manifest.json"
OUTPUT_ALIASES = {
    "do_thi_day_dac_GiaiPhong-GiapBat": "output_giai_phong_rt_full_sionna_final_physics",
}
CONFIG_ALIASES = {
    "do_thi_day_dac_GiaiPhong-GiapBat": "config_giai_phong_rt_full_sionna_final_physics.yaml",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Sionna RT for already prepared/exported OSM scenes.")
    parser.add_argument("--skip-scene-id", action="append", default=[])
    parser.add_argument("--stall-timeout-min", type=float, default=45.0)
    parser.add_argument("--scene-timeout-hours", type=float, default=8.0)
    parser.add_argument("--log", default=str(PIPELINE / "prepared_sionna_batch.log"))
    return parser.parse_args()


def output_dir_name_for(scene_id: str) -> str:
    return OUTPUT_ALIASES.get(scene_id, f"output_{scene_id}_full_sionna_final_physics")


def config_path_for(scene_id: str) -> Path:
    filename = CONFIG_ALIASES.get(scene_id, f"config_{scene_id}_final_physics.yaml")
    return PIPELINE / "config" / filename


def run_logged(cmd: list[str], cwd: Path, log_path: Path, timeout_s: float | None = None) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        completed = subprocess.run(cmd, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT, timeout=timeout_s)
    return int(completed.returncode)


def evaluate(scene: dict, output_dir: Path) -> int:
    return run_logged(
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
        output_dir / "evaluate.log",
        timeout_s=600,
    )


def run_sionna_scene(scene: dict, output_dir: Path, stall_timeout_min: float, scene_timeout_hours: float, log) -> bool:
    config = config_path_for(scene["id"])
    if not config.exists():
        print(f"{scene['id']}: missing config {config}", file=log, flush=True)
        return False
    for required in ("scene.xml", "scene_metadata.json"):
        if not (output_dir / required).exists():
            print(f"{scene['id']}: missing prepared file {output_dir / required}", file=log, flush=True)
            return False

    stdout_path = output_dir / "sionna_final_physics.log"
    stderr_path = output_dir / "sionna_final_physics.err"
    cmd = [sys.executable, str(PIPELINE / "tools" / "run_sionna_rt_preloaded.py"), "--config", str(config)]
    with stdout_path.open("w", encoding="utf-8", errors="replace") as stdout, stderr_path.open("w", encoding="utf-8", errors="replace") as stderr:
        proc = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT), stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL)
        print(f"{scene['id']}: Sionna PID {proc.pid}", file=log, flush=True)
        start = time.time()
        last_activity = time.time()
        last_size = -1
        while proc.poll() is None:
            time.sleep(60)
            size = stdout_path.stat().st_size if stdout_path.exists() else 0
            newest_csv = max((p.stat().st_mtime for p in output_dir.glob("mpc_gnb_*.csv")), default=0.0)
            activity = max(stdout_path.stat().st_mtime if stdout_path.exists() else 0.0, newest_csv)
            if size != last_size or activity > last_activity:
                last_activity = max(last_activity, activity)
                last_size = size
            if time.time() - last_activity > stall_timeout_min * 60.0:
                print(f"{scene['id']}: stall timeout after {stall_timeout_min:.1f} min", file=log, flush=True)
                proc.terminate()
                time.sleep(10)
                if proc.poll() is None:
                    proc.kill()
                return False
            if time.time() - start > scene_timeout_hours * 3600.0:
                print(f"{scene['id']}: scene timeout after {scene_timeout_hours:.1f} h", file=log, flush=True)
                proc.terminate()
                time.sleep(10)
                if proc.poll() is None:
                    proc.kill()
                return False
        print(f"{scene['id']}: Sionna exit code {proc.returncode}", file=log, flush=True)
        return proc.returncode == 0


def aggregate(scene_ids: list[str]) -> None:
    rows = []
    for scene_id in scene_ids:
        output_dir = PIPELINE / output_dir_name_for(scene_id)
        eval_path = output_dir / "technical_ns3_evaluation.json"
        if eval_path.exists():
            rows.append(json.loads(eval_path.read_text(encoding="utf-8")))
    (PIPELINE / "output_all_scenes_final_physics_summary.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    lines = ["# All Scenes Final Physics Summary", ""]
    lines.append("| Scene | Terrain | Status | Track m | RX | gNB | Key issues |")
    lines.append("|---|---|---:|---:|---:|---:|---|")
    for row in rows:
        issues = "; ".join(row.get("issues", [])) or "none"
        lines.append(
            f"| {row['scene_id']} | {row.get('terrain_type','')} | {row.get('status','')} | "
            f"{float(row.get('track_length_m') or 0):.1f} | {row.get('rx_samples',0)} | {len(row.get('gnb_positions_m', []))} | {issues} |"
        )
    (PIPELINE / "output_all_scenes_final_physics_summary.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    scenes = json.loads(CATALOG.read_text(encoding="utf-8"))
    skipped = set(args.skip_scene_id)
    with Path(args.log).open("w", encoding="utf-8", errors="replace") as log:
        print("Prepared Sionna batch started", file=log, flush=True)
        for scene in scenes:
            output_dir = PIPELINE / output_dir_name_for(scene["id"])
            if scene["id"] in skipped:
                if (output_dir / "trace_manifest.json").exists():
                    print(f"{scene['id']}: evaluating skipped pre-existing output", file=log, flush=True)
                    evaluate(scene, output_dir)
                continue
            print(f"=== Running {scene['id']} ===", file=log, flush=True)
            ok = run_sionna_scene(scene, output_dir, args.stall_timeout_min, args.scene_timeout_hours, log)
            if ok:
                eval_code = evaluate(scene, output_dir)
                print(f"{scene['id']}: evaluate exit code {eval_code}", file=log, flush=True)
            else:
                (output_dir / "sionna_batch_error.txt").write_text("Sionna run failed or timed out", encoding="utf-8")
        aggregate([scene["id"] for scene in scenes])
        print("Prepared Sionna batch complete", file=log, flush=True)


if __name__ == "__main__":
    main()
