from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml


EXPERIMENT_ROOT = Path(__file__).resolve().parent
PIPELINE_ROOT = EXPERIMENT_ROOT.parents[1]
SCENE_MANIFEST = PIPELINE_ROOT / "vietnam_railway_osm_scenes" / "scene_manifest.json"
PYTHON_SIONNA = Path(os.environ.get("SIONNA_PYTHON", sys.executable))
SPEED_KMH = 350.0
SPEED_MPS = SPEED_KMH / 3.6
RESOLUTIONS_M = (25.0, 5.0, 2.0)
SCENE_SELECTORS = {
    "E2": {
        "terrain_type": "do_thi_cau_song",
        "class": "river crossing",
    },
    "E6": {
        "terrain_type": "deo_nui_ven_bien",
        "class": "mountainous pass",
    },
}


def resolve_selected_scenes() -> dict[str, dict]:
    """Resolve experiment labels through the project manifest, never filesystem aliases."""
    records = json.loads(SCENE_MANIFEST.read_text(encoding="utf-8"))
    selected: dict[str, dict] = {}
    for label, selector in SCENE_SELECTORS.items():
        matches = [record for record in records if record.get("terrain_type") == selector["terrain_type"]]
        if len(matches) != 1:
            raise RuntimeError(f"{label}: expected exactly one manifest scene for {selector}, found {len(matches)}")
        record = matches[0]
        scene_id = record["id"]
        selected[label] = {
            "id": scene_id,
            "class": selector["class"],
            "terrain_type": record["terrain_type"],
            "manifest_record": record,
            "baseline": f"output_{scene_id}_full_sionna_final_physics",
            "config": f"config_{scene_id}_final_physics.yaml",
        }
    return selected


SCENES = resolve_selected_scenes()
SIONNA_RUNTIME_PROVENANCE = {
    "python_sionna_runtime": "3.13.9",
    "sionna_version": "unreported_by_installed_source_package_no_distribution_metadata",
    "mitsuba_version": "3.8.0",
    "drjit_version": "1.3.1",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(raw).hexdigest()


def cumulative_distances(points: list[list[float]]) -> list[float]:
    distances = [0.0]
    for previous, current in zip(points, points[1:]):
        distances.append(distances[-1] + math.dist(previous[:3], current[:3]))
    return distances


def interpolate_polyline(points: list[list[float]], spacing_m: float) -> list[list[float]]:
    """Subdivide every baseline segment, preserving every vertex and both endpoints."""
    if spacing_m == 25.0:
        return [[float(value) for value in point[:3]] for point in points]
    result = [[float(value) for value in points[0][:3]]]
    for left, right in zip(points, points[1:]):
        segment_length = math.dist(left[:3], right[:3])
        subdivisions = max(1, int(math.ceil(segment_length / spacing_m)))
        for step in range(1, subdivisions + 1):
            alpha = step / subdivisions
            result.append([
                float(left[axis]) + alpha * (float(right[axis]) - float(left[axis]))
                for axis in range(3)
            ])
    return result


def polyline_geometry_checks(candidate: list[list[float]], baseline: list[list[float]], tolerance_m: float = 1e-6) -> dict:
    """Independently verify ordered projection onto the legacy trajectory."""
    cumulative = cumulative_distances(baseline)
    last_progress = -tolerance_m
    max_deviation = 0.0
    ordered = True
    on_polyline = True
    for point in candidate:
        projections: list[tuple[float, float]] = []
        for index, (left, right) in enumerate(zip(baseline, baseline[1:])):
            vector = [float(right[axis]) - float(left[axis]) for axis in range(3)]
            offset = [float(point[axis]) - float(left[axis]) for axis in range(3)]
            squared_length = sum(value * value for value in vector)
            if squared_length <= 0.0:
                continue
            fraction = min(1.0, max(0.0, sum(offset[axis] * vector[axis] for axis in range(3)) / squared_length))
            projected = [float(left[axis]) + fraction * vector[axis] for axis in range(3)]
            deviation = math.dist(point[:3], projected)
            progress = cumulative[index] + fraction * math.sqrt(squared_length)
            projections.append((deviation, progress))
        minimum_deviation = min(deviation for deviation, _ in projections)
        max_deviation = max(max_deviation, minimum_deviation)
        valid_progresses = sorted(
            progress for deviation, progress in projections
            if deviation <= tolerance_m and progress >= last_progress - tolerance_m
        )
        if minimum_deviation > tolerance_m:
            on_polyline = False
        if not valid_progresses:
            ordered = False
        else:
            last_progress = valid_progresses[0]

    preserved_indices: list[int] = []
    search_from = 0
    for vertex in baseline:
        match = next((index for index in range(search_from, len(candidate)) if math.dist(candidate[index][:3], vertex[:3]) <= tolerance_m), None)
        if match is None:
            break
        preserved_indices.append(match)
        search_from = match + 1
    baseline_length = cumulative[-1]
    candidate_length = cumulative_distances(candidate)[-1]
    route_difference = candidate_length - baseline_length
    vertices_preserved = len(preserved_indices) == len(baseline)
    return {
        "baseline_vertices_preserved_in_order": vertices_preserved,
        "all_samples_on_baseline_polyline": on_polyline,
        "polyline_progress_nondecreasing": ordered,
        "max_deviation_from_baseline_polyline_m": max_deviation,
        "route_length_difference_from_25m_m": route_difference,
        "same_polyline_geometry_as_25m": (
            vertices_preserved and on_polyline and ordered and abs(route_difference) <= tolerance_m
        ),
    }


def case_dir(scene: str, resolution: float) -> Path:
    return EXPERIMENT_ROOT / "sionna" / scene / f"{resolution:g}m"


def config_path(scene: str, resolution: float) -> Path:
    return EXPERIMENT_ROOT / "configs" / f"config_{scene}_{resolution:g}m.yaml"


def load_scene_catalog() -> dict[str, dict]:
    records = json.loads(SCENE_MANIFEST.read_text(encoding="utf-8"))
    return {record["id"]: record for record in records}


def physics_subset(config: dict) -> dict:
    return {
        "frequency_hz": config["simulation"]["frequency_hz"],
        "train_speed_kmh": config["simulation"]["train_speed_kmh"],
        "train": config["train"],
        "ray_tracing": config["ray_tracing"],
        "antenna": config["antenna"],
        "base_stations": config.get("base_stations", []),
    }


def prepare_case(scene: str, resolution: float, force: bool = False) -> dict:
    spec = SCENES[scene]
    catalog = load_scene_catalog()
    if spec["id"] not in catalog:
        raise RuntimeError(f"Scene {spec['id']} is absent from {SCENE_MANIFEST}")
    baseline_dir = PIPELINE_ROOT / spec["baseline"]
    baseline_metadata_path = baseline_dir / "scene_metadata.json"
    baseline_config_path = PIPELINE_ROOT / "config" / spec["config"]
    baseline_scene_path = baseline_dir / "scene.xml"
    for required in (baseline_metadata_path, baseline_config_path, baseline_scene_path):
        if not required.exists():
            raise FileNotFoundError(required)

    out_dir = case_dir(scene, resolution)
    out_dir.mkdir(parents=True, exist_ok=True)
    metadata_out = out_dir / "scene_metadata.json"
    config_out = config_path(scene, resolution)
    if metadata_out.exists() and config_out.exists() and not force:
        manifest_path = out_dir / "case_manifest.json"
        if manifest_path.exists():
            provenance = json.loads(manifest_path.read_text(encoding="utf-8"))
            changed = False
            for key, value in SIONNA_RUNTIME_PROVENANCE.items():
                if key not in provenance:
                    provenance[key] = value
                    changed = True
            if "status" not in provenance:
                if resolution == 25.0:
                    provenance["status"] = "reused_legacy_baseline_complete"
                elif (out_dir / "trace_manifest.json").exists() and provenance.get("exit_code") == 0:
                    provenance["status"] = "complete"
                elif "exit_code" in provenance and provenance.get("exit_code") != 0:
                    provenance["status"] = "failed"
                else:
                    provenance["status"] = "prepared"
                changed = True
            if resolution == 25.0:
                baseline_outputs = [
                    *sorted(baseline_dir.glob("mpc_gnb_*.csv")),
                    baseline_dir / "scene_metadata.json",
                    *([baseline_dir / "trace_manifest.json"] if (baseline_dir / "trace_manifest.json").exists() else []),
                ]
                defaults = {
                    "execution_policy": "reused legacy baseline without regeneration",
                    "command_used": "unavailable_for_legacy_baseline; isolated runner skips 25 m unless --force",
                    "runtime_s": "unavailable_for_legacy_baseline",
                    "exit_code": "not_rerun",
                    "output_file_hashes": {path.name: sha256(path) for path in baseline_outputs},
                }
                for key, value in defaults.items():
                    if key not in provenance:
                        provenance[key] = value
                        changed = True
                expected_hashes = {path.name: sha256(path) for path in baseline_outputs}
                if provenance.get("output_file_hashes") != expected_hashes:
                    provenance["output_file_hashes"] = expected_hashes
                    changed = True
            elif (out_dir / "trace_manifest.json").exists() and provenance.get("exit_code") == 0:
                mpc_outputs = sorted(out_dir.glob("mpc_gnb_*.csv"))
                if len(mpc_outputs) == int(provenance["gNB_count"]):
                    final_outputs = [*mpc_outputs, out_dir / "trace_manifest.json", metadata_out]
                    expected_hashes = {path.name: sha256(path) for path in final_outputs}
                    if provenance.get("output_file_hashes") != expected_hashes:
                        provenance["output_file_hashes"] = expected_hashes
                        changed = True
                    if provenance.get("status") != "complete":
                        provenance["status"] = "complete"
                        changed = True
            if changed:
                manifest_path.write_text(json.dumps(provenance, indent=2), encoding="utf-8")
        return json.loads(metadata_out.read_text(encoding="utf-8"))

    baseline_metadata = json.loads(baseline_metadata_path.read_text(encoding="utf-8"))
    baseline_points = baseline_metadata["rx_trajectory_samples"]
    refined_points = interpolate_polyline(baseline_points, resolution)
    metadata = dict(baseline_metadata)
    metadata["rx_trajectory_samples"] = refined_points
    metadata["sample_spacing_m"] = resolution
    metadata["resolution_experiment"] = {
        "created_utc": utc_now(),
        "scene_label": scene,
        "scene_class": spec["class"],
        "requested_spacing_m": resolution,
        "resampling_method": "piecewise-linear arc-length resampling of the baseline trajectory polyline",
        "baseline_metadata": str(baseline_metadata_path),
        "baseline_metadata_sha256": sha256(baseline_metadata_path),
        "baseline_scene_xml": str(baseline_scene_path),
        "baseline_scene_xml_sha256": sha256(baseline_scene_path),
        "gNB_positions_preserved_from_baseline": True,
        "geometry_and_mitsuba_scene_reused": True,
    }
    metadata_out.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    config = yaml.safe_load(baseline_config_path.read_text(encoding="utf-8"))
    config.setdefault("external_scene", {})["trajectory_spacing_m"] = resolution
    config["scenario"]["name"] = f"rt_resolution_sensitivity_{scene}_{resolution:g}m"
    config["paths"] = {
        "blend_file": str((baseline_dir / Path(config["paths"]["blend_file"]).name).resolve()),
        "mitsuba_xml": str(baseline_scene_path.resolve()),
        "mesh_dir": str((baseline_dir / "meshes").resolve()),
        "trace_csv": str((out_dir / "ns3_trace.csv").resolve()),
        "trace_csv_pattern": str((out_dir / "{station}.csv").resolve()),
        "trace_manifest": str((out_dir / "trace_manifest.json").resolve()),
        "doppler_plot": str((out_dir / "doppler_vs_time.png").resolve()),
        "doppler_plot_pattern": str((out_dir / "{station}_doppler_vs_time.png").resolve()),
        "path_count_plot": str((out_dir / "path_count_vs_time.png").resolve()),
        "path_count_plot_pattern": str((out_dir / "{station}_path_count_vs_time.png").resolve()),
        "scene_metadata": str(metadata_out.resolve()),
    }
    config_out.parent.mkdir(parents=True, exist_ok=True)
    config_out.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    provenance = {
        "timestamp_utc": utc_now(),
        "status": "reused_legacy_baseline_complete" if resolution == 25.0 else "prepared",
        "git_commit": None,
        "git_note": "phase1_pipeline is not a Git worktree",
        "scene": scene,
        "scene_id": spec["id"],
        "scene_class": spec["class"],
        "resolution_m": resolution,
        "train_speed_kmh": SPEED_KMH,
        "seed": 42,
        "config": str(config_out),
        "config_hash": sha256(config_out),
        "physics_hash": canonical_hash(physics_subset(config)),
        "gNB_count": len(metadata.get("all_gnb_positions_m", [])),
        "trajectory_sample_count": len(refined_points),
        "input_file_hashes": {
            "baseline_config": sha256(baseline_config_path),
            "baseline_metadata": sha256(baseline_metadata_path),
            "scene_xml": sha256(baseline_scene_path),
        },
        "python_version": platform.python_version(),
        **SIONNA_RUNTIME_PROVENANCE,
        "host": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
    }
    (out_dir / "case_manifest.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    return metadata


def trajectory_metrics(scene: str, resolution: float) -> dict:
    metadata = json.loads((case_dir(scene, resolution) / "scene_metadata.json").read_text(encoding="utf-8"))
    points = metadata["rx_trajectory_samples"]
    cumulative = cumulative_distances(points)
    spacings = [right - left for left, right in zip(cumulative, cumulative[1:])]
    intervals = [spacing / SPEED_MPS * 1000.0 for spacing in spacings]
    return {
        "scene": scene,
        "scene_id": SCENES[scene]["id"],
        "route_length_m": cumulative[-1],
        "requested_spacing_m": resolution,
        "number_of_samples": len(points),
        "actual_mean_spacing_m": sum(spacings) / len(spacings),
        "actual_min_spacing_m": min(spacings),
        "actual_max_spacing_m": max(spacings),
        "train_speed_mps": SPEED_MPS,
        "mean_temporal_interval_ms": sum(intervals) / len(intervals),
        "min_temporal_interval_ms": min(intervals),
        "max_temporal_interval_ms": max(intervals),
        "first_position": json.dumps(points[0]),
        "last_position": json.dumps(points[-1]),
        "timestamp_strictly_increasing": all(value > 0 for value in intervals),
        "unnecessary_duplicate_samples": sum(math.dist(a, b) <= 1e-9 for a, b in zip(points, points[1:])),
    }


def validate_trajectories() -> Path:
    rows = []
    for scene in SCENES:
        baseline_start = baseline_end = baseline_points = None
        for resolution in RESOLUTIONS_M:
            prepare_case(scene, resolution)
            row = trajectory_metrics(scene, resolution)
            points = json.loads((case_dir(scene, resolution) / "scene_metadata.json").read_text(encoding="utf-8"))["rx_trajectory_samples"]
            if baseline_start is None:
                baseline_start, baseline_end, baseline_points = points[0], points[-1], points
            row["same_start_as_25m"] = math.dist(points[0], baseline_start) <= 1e-9
            row["same_end_as_25m"] = math.dist(points[-1], baseline_end) <= 1e-9
            row.update(polyline_geometry_checks(points, baseline_points))
            rows.append(row)
    output = EXPERIMENT_ROOT / "analysis" / "trajectory_resolution_validation.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return output


def run_raytrace(scene: str, resolution: float, force: bool = False) -> None:
    if resolution == 25.0 and not force:
        print("25-m baseline is reused; pass --force to regenerate it in the isolated directory.")
        return
    out_dir = case_dir(scene, resolution)
    prepare_case(scene, resolution, force=False)
    trace_manifest = out_dir / "trace_manifest.json"
    if trace_manifest.exists() and not force:
        print(f"Valid trace manifest exists, skipping: {trace_manifest}")
        return
    command = [str(PYTHON_SIONNA), str(PIPELINE_ROOT / "tools" / "run_sionna_rt_preloaded.py"), "--config", str(config_path(scene, resolution))]
    log_path = EXPERIMENT_ROOT / "logs" / f"raytrace_{scene}_{resolution:g}m.log"
    err_path = EXPERIMENT_ROOT / "logs" / f"raytrace_{scene}_{resolution:g}m.err"
    manifest_path = out_dir / "case_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update({"status": "running", "started_utc": utc_now(), "command_used": command})
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    started = time.time()
    with log_path.open("a", encoding="utf-8") as log, err_path.open("a", encoding="utf-8") as err:
        log.write(f"\n[{utc_now()}] COMMAND: {' '.join(command)}\n")
        completed = subprocess.run(command, cwd=PIPELINE_ROOT.parent, stdout=log, stderr=err)
    mpc_outputs = sorted(out_dir.glob("mpc_gnb_*.csv"))
    expected_gnbs = int(manifest["gNB_count"])
    postconditions_ok = trace_manifest.exists() and len(mpc_outputs) == expected_gnbs
    success = completed.returncode == 0 and postconditions_ok
    manifest.update({
        "status": "complete" if success else "failed",
        "finished_utc": utc_now(),
        "runtime_s": time.time() - started,
        "exit_code": completed.returncode,
        "postconditions": {
            "trace_manifest_present": trace_manifest.exists(),
            "expected_gnb_files": expected_gnbs,
            "actual_gnb_files": len(mpc_outputs),
        },
    })
    if success:
        output_files = [*mpc_outputs, trace_manifest, out_dir / "scene_metadata.json"]
        manifest["output_file_hashes"] = {path.name: sha256(path) for path in output_files}
    else:
        manifest["postcondition_error"] = "subprocess failure or incomplete finalized RT artifact set"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if not success:
        raise RuntimeError(f"Ray tracing failed or finalized artifacts are incomplete; see {log_path} and {err_path}")


def run_pilot(scene: str, resolution: float, force: bool = False) -> dict:
    """Run three representative snapshots for one gNB without changing RT physics."""
    prepare_case(scene, resolution)
    source_config = yaml.safe_load(config_path(scene, resolution).read_text(encoding="utf-8"))
    source_metadata = json.loads((case_dir(scene, resolution) / "scene_metadata.json").read_text(encoding="utf-8"))
    points = source_metadata["rx_trajectory_samples"]
    selected = [points[0], points[len(points) // 2], points[-1]]
    pilot_dir = EXPERIMENT_ROOT / "sionna" / scene / f"{resolution:g}m_pilot"
    pilot_dir.mkdir(parents=True, exist_ok=True)
    pilot_metadata = dict(source_metadata)
    pilot_metadata["rx_trajectory_samples"] = selected
    pilot_metadata["pilot_only"] = True
    metadata_path = pilot_dir / "scene_metadata.json"
    metadata_path.write_text(json.dumps(pilot_metadata, indent=2), encoding="utf-8")
    source_config["base_stations"] = source_config["base_stations"][:1]
    source_config["paths"].update({
        "trace_csv": str((pilot_dir / "ns3_trace.csv").resolve()),
        "trace_csv_pattern": str((pilot_dir / "{station}.csv").resolve()),
        "trace_manifest": str((pilot_dir / "trace_manifest.json").resolve()),
        "doppler_plot": str((pilot_dir / "doppler_vs_time.png").resolve()),
        "doppler_plot_pattern": str((pilot_dir / "{station}_doppler_vs_time.png").resolve()),
        "path_count_plot": str((pilot_dir / "path_count_vs_time.png").resolve()),
        "path_count_plot_pattern": str((pilot_dir / "{station}_path_count_vs_time.png").resolve()),
        "scene_metadata": str(metadata_path.resolve()),
    })
    pilot_config = EXPERIMENT_ROOT / "configs" / f"config_{scene}_{resolution:g}m_pilot.yaml"
    pilot_config.write_text(yaml.safe_dump(source_config, sort_keys=False), encoding="utf-8")
    result_path = pilot_dir / "pilot_result.json"
    if result_path.exists() and not force:
        return json.loads(result_path.read_text(encoding="utf-8"))
    command = [str(PYTHON_SIONNA), str(PIPELINE_ROOT / "tools" / "run_sionna_rt_preloaded.py"), "--config", str(pilot_config)]
    log_path = EXPERIMENT_ROOT / "logs" / f"pilot_{scene}_{resolution:g}m.log"
    err_path = EXPERIMENT_ROOT / "logs" / f"pilot_{scene}_{resolution:g}m.err"
    started = time.time()
    with log_path.open("w", encoding="utf-8") as log, err_path.open("w", encoding="utf-8") as err:
        completed = subprocess.run(command, cwd=PIPELINE_ROOT.parent, stdout=log, stderr=err)
    runtime = time.time() - started
    if completed.returncode != 0:
        raise RuntimeError(f"Pilot failed; see {log_path} and {err_path}")
    result = {
        "scene": scene, "resolution_m": resolution, "pilot_snapshots": len(selected), "pilot_gnbs": 1,
        "pilot_runtime_s": runtime, "full_snapshots": len(points),
        "full_gnbs": len(source_metadata.get("all_gnb_positions_m", [])),
        "linear_runtime_estimate_s": runtime / len(selected) * len(points) * len(source_metadata.get("all_gnb_positions_m", [])),
        "command": command, "timestamp_utc": utc_now(),
    }
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def dry_run(scene: str | None, resolution: float | None, stage: str) -> None:
    scenes = [scene] if scene else list(SCENES)
    resolutions = [resolution] if resolution is not None else list(RESOLUTIONS_M)
    for item_scene in scenes:
        for item_resolution in resolutions:
            print(f"{stage}: scene={item_scene} ({SCENES[item_scene]['id']}), resolution={item_resolution:g} m, output={case_dir(item_scene, item_resolution)}")


def prepare_ns3(require_complete: bool = False, force: bool = False) -> None:
    command = [sys.executable, str(EXPERIMENT_ROOT / "prepare_ns3_package.py")]
    if require_complete:
        command.append("--require-complete")
    if force:
        command.append("--force")
    subprocess.run(command, check=True)


def resolve_ns3_repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit.resolve()
    if os.name == "nt":
        manifest = json.loads((EXPERIMENT_ROOT / "experiment_manifest.json").read_text(encoding="utf-8"))
        return Path(manifest["ns3_source_archive_windows"])
    return Path.home() / "siolena-src"


def run_ns3_matrix(
    repo_root: Path | None,
    scene: str | None,
    resolution: float | None,
    mode: str | None,
    resume: bool,
    force: bool,
    dry_run_only: bool,
) -> None:
    repo = resolve_ns3_repo(repo_root)
    if not repo.exists():
        raise FileNotFoundError(f"Audited ns-3 repository not found: {repo}")
    command = [
        sys.executable,
        str(EXPERIMENT_ROOT / "ns3_package" / "run_resolution_matrix.py"),
        "--repo-root", str(repo),
        "--experiment-root", str(EXPERIMENT_ROOT),
    ]
    if scene:
        command.extend(["--scene", scene])
    if resolution is not None:
        command.extend(["--resolution", f"{resolution:g}"])
    if mode:
        command.extend(["--mode", mode])
    if dry_run_only:
        command.append("--dry-run")
    elif os.name == "nt":
        raise RuntimeError(
            "The audited executable is a Linux binary. Actual ns-3 execution requires native Ubuntu/WSL2; "
            "use --dry-run on Windows or follow UBUNTU_NS3_RUN_INSTRUCTIONS.md."
        )
    if resume and not force:
        command.append("--resume")
    subprocess.run(command, cwd=EXPERIMENT_ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the isolated Sionna RT spatial-resolution sensitivity experiment.")
    parser.add_argument("--scene", choices=sorted(SCENES))
    parser.add_argument("--resolution", type=float, choices=RESOLUTIONS_M)
    parser.add_argument("--stage", choices=("prepare", "validate", "pilot", "raytrace", "convert", "ns3", "analyze", "plot", "verify", "all"), required=True)
    parser.add_argument("--a3-mode", choices=("aggressive", "balanced", "conservative"))
    parser.add_argument("--ns3-repo-root", type=Path, help="Audited ns-3.44/5G-LENA repository (defaults are platform-specific)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.dry_run:
        if args.stage == "ns3":
            run_ns3_matrix(args.ns3_repo_root, args.scene, args.resolution, args.a3_mode, args.resume, args.force, True)
            return
        dry_run(args.scene, args.resolution, args.stage)
        return
    if args.stage == "validate":
        print(validate_trajectories())
        return
    if args.stage == "convert":
        prepare_ns3(require_complete=True, force=args.force)
        return
    if args.stage == "ns3":
        run_ns3_matrix(args.ns3_repo_root, args.scene, args.resolution, args.a3_mode, args.resume, args.force, False)
        return
    if args.stage in {"analyze", "plot"}:
        subprocess.run([sys.executable, str(EXPERIMENT_ROOT / "analyze_results.py")], check=True)
        return
    if args.stage == "verify":
        subprocess.run([sys.executable, str(EXPERIMENT_ROOT / "verify_experiment.py"), "--strict"], check=True)
        return
    if args.stage == "pilot":
        if not args.scene or args.resolution is None:
            raise RuntimeError("--stage pilot requires --scene and --resolution")
        print(json.dumps(run_pilot(args.scene, args.resolution, force=args.force), indent=2))
        return
    scenes = [args.scene] if args.scene else list(SCENES)
    resolutions = [args.resolution] if args.resolution is not None else list(RESOLUTIONS_M)
    for scene in scenes:
        for resolution in resolutions:
            prepare_case(scene, resolution, force=args.force)
            if args.stage in {"raytrace", "all"}:
                run_raytrace(scene, resolution, force=args.force)
    validate_trajectories()
    if args.stage == "all":
        prepare_ns3(require_complete=True, force=args.force)
        if os.name != "nt":
            run_ns3_matrix(
                args.ns3_repo_root, args.scene, args.resolution, args.a3_mode,
                args.resume, args.force, False,
            )
            subprocess.run([sys.executable, str(EXPERIMENT_ROOT / "analyze_results.py")], check=True)
            subprocess.run([sys.executable, str(EXPERIMENT_ROOT / "verify_experiment.py"), "--strict"], check=True)
        else:
            print(
                "All Windows/Sionna stages are complete. The verified package is ready for native Ubuntu/WSL2; "
                "run --stage ns3 there, then --stage analyze and --stage verify."
            )


if __name__ == "__main__":
    main()
