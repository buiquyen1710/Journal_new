from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from run_experiment import (
    PIPELINE_ROOT,
    SCENES as SELECTED_SCENES,
    canonical_hash,
    physics_subset,
)


ROOT = Path(__file__).resolve().parent
SCENES = tuple(SELECTED_SCENES)
SPACINGS = (25, 5, 2)
MODES = ("aggressive", "balanced", "conservative")
EXPECTED_A3 = {
    "aggressive": {"hom_db": 1, "ttt_ms": 40},
    "balanced": {"hom_db": 3, "ttt_ms": 160},
    "conservative": {"hom_db": 5, "ttt_ms": 320},
}

KPI_REQUIRED = {
    "scene", "scene_class", "route_length_km", "resolution_m", "rt_interval_ms",
    "measurement_interval_ms", "a3_mode", "hom_db", "ttt_ms", "mean_sinr_db",
    "p5_sinr_db", "radio_outage_ratio_pct", "handover_count", "pingpong_count",
    "handover_per_km", "pingpong_per_km", "num_rt_snapshots", "num_valid_snapshots",
    "seed", "config_hash", "trace_hash", "runtime_s",
}
EVENT_REQUIRED = {
    "scene", "resolution_m", "operating_point", "event_index", "handover_start_time_s",
    "handover_end_time_s", "source_gnb", "target_gnb", "train_position_m", "train_x",
    "train_y", "SINR_before", "SINR_after",
    "start_event_join", "context_join",
}
CASE_METADATA_REQUIRED = {
    "case_id", "created_utc", "finished_utc", "scene", "scene_id", "scene_class",
    "resolution_m", "mode", "hom_db", "ttt_ms", "rng_seed", "rng_run", "rt_seed",
    "train_speed_kmh", "carrier_frequency_hz", "measurement_controller_polling_ms",
    "warmup_exclusion_s", "physics_hash", "gnb_count", "trajectory_sample_count",
    "rt_sample_count", "sionna_version", "sionna_python_version", "ns3_version",
    "runner_python_version", "git_commit", "config", "physics_parameters",
    "fiveg_lena_version", "ns3_git_commit", "program_source_sha256", "binary_sha256",
    "ns3_shared_library_count", "ns3_shared_library_aggregate_sha256", "executor",
    "runtime_config_sha256", "sionna_case_manifest_sha256", "sionna_config_sha256",
    "converted_parameter_sha256", "input_mpc_aggregate_sha256", "sionna_input_file_hashes",
    "sionna_output_file_hashes", "command", "command_shell", "runtime_s", "exit_code",
    "host", "output_file_hashes",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def aggregate_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.name.encode())
        digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def csv_columns(path: Path) -> set[str]:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    with path.open(newline="", encoding="utf-8") as handle:
        return set(csv.DictReader(handle).fieldnames or [])


def finite_number(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def ns3_provenance_checks(
    root: Path,
    scene: str,
    spacing: int,
    metadata: dict,
    experiment_manifest: dict,
) -> dict[str, bool]:
    sionna_manifest_path = root / "sionna" / scene / f"{spacing}m" / "case_manifest.json"
    sionna_manifest = json.loads(sionna_manifest_path.read_text(encoding="utf-8")) if sionna_manifest_path.exists() else {}
    sionna_config_path = root / "configs" / f"config_{scene}_{spacing}m.yaml"
    ubuntu_config_path = root / "ns3_package" / "configs" / f"{scene}_{spacing}m.json"
    runtime_config_path = root / "ns3_package" / "configs_runtime" / f"{scene}_{spacing}m.json"
    parameter_path = root / "ns3_ready" / f"RTSensitivity_{scene}_{spacing}m" / "Input" / "paraCfgCurrent.txt"
    ubuntu_config = json.loads(ubuntu_config_path.read_text(encoding="utf-8")) if ubuntu_config_path.exists() else {}
    input_mpc_files = [
        root / "raw_mpc" / scene / f"{spacing}m" / name
        for name in ubuntu_config.get("mpc_csv_files", [])
    ]
    physics_parameters = metadata.get("physics_parameters", {})
    executor = metadata.get("executor", {})
    expected_bridge = experiment_manifest.get("local_wsl2_executor", {})
    executor_runtime_ok = executor.get("type") == "native" or (
        executor.get("type") == "docker-desktop-wsl2"
        and all(executor.get(key) == expected_bridge.get(key) for key in (
            "type", "distro", "kernel", "loader_sha256",
            "system_runtime_file_count", "system_runtime_aggregate_sha256",
            "private_runtime_file_count", "private_runtime_aggregate_sha256",
        ))
        and bool(executor.get("linux_repo_root"))
        and bool(executor.get("linux_experiment_root"))
        and bool(executor.get("loader"))
    )
    return {
        "software": (
            metadata.get("ns3_version") == experiment_manifest.get("ns3_version")
            and metadata.get("fiveg_lena_version") == experiment_manifest.get("fiveg_lena_version")
            and metadata.get("ns3_git_commit") == experiment_manifest.get("ns3_git_commit")
            and metadata.get("program_source_sha256") == experiment_manifest.get("ns3_program_sha256")
            and metadata.get("binary_sha256") == experiment_manifest.get("ns3_binary_sha256")
            and int(metadata.get("ns3_shared_library_count", -1)) == int(experiment_manifest.get("ns3_shared_library_count", -2))
            and metadata.get("ns3_shared_library_aggregate_sha256") == experiment_manifest.get("ns3_shared_library_aggregate_sha256")
        ),
        "sionna_manifest": (
            bool(sionna_manifest) and sionna_config_path.exists()
            and metadata.get("sionna_case_manifest_sha256") == sha256(sionna_manifest_path)
            and metadata.get("sionna_config_sha256") == sha256(sionna_config_path)
            and metadata.get("sionna_input_file_hashes") == sionna_manifest.get("input_file_hashes")
            and metadata.get("sionna_output_file_hashes") == sionna_manifest.get("output_file_hashes")
            and metadata.get("physics_hash") == sionna_manifest.get("physics_hash")
            and int(metadata.get("gnb_count", -1)) == int(sionna_manifest.get("gNB_count", -2))
            and int(metadata.get("trajectory_sample_count", -1)) == int(sionna_manifest.get("trajectory_sample_count", -2))
        ),
        "runtime_config": runtime_config_path.exists() and metadata.get("runtime_config_sha256") == sha256(runtime_config_path),
        "converted_parameter": parameter_path.exists() and metadata.get("converted_parameter_sha256") == sha256(parameter_path),
        "raw_mpc": (
            bool(input_mpc_files) and all(path.exists() for path in input_mpc_files)
            and metadata.get("input_mpc_aggregate_sha256") == aggregate_hash(input_mpc_files)
        ),
        "radio_physics": (
            float(physics_parameters.get("carrier_frequency_hz", math.nan)) == 30e9
            and float(physics_parameters.get("bandwidth_mhz", math.nan)) == 400.0
            and int(physics_parameters.get("numerology", -1)) == 3
            and int(physics_parameters.get("beam_period_ms", -1)) == 100
            and physics_parameters.get("beamforming_method") == "ns3::DirectPathBeamforming"
            and physics_parameters.get("ideal_rrc") is True
        ),
        "executor_runtime": executor_runtime_ok,
    }


def add(checks: list[dict], name: str, status: str, evidence: object) -> None:
    checks.append({"name": name, "status": status, "evidence": evidence})


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed completion audit for the RT resolution sensitivity experiment.")
    parser.add_argument("--strict", action="store_true", help="Return nonzero unless every required check passes")
    args = parser.parse_args()
    checks: list[dict] = []
    fine_manifests_complete = all(
        (ROOT / "sionna" / scene / f"{spacing}m" / "trace_manifest.json").exists()
        for scene in SCENES for spacing in (5, 2)
    )

    trajectory = read_csv(ROOT / "analysis" / "trajectory_resolution_validation.csv")
    trajectory_required = {
        "scene", "scene_id", "route_length_m", "requested_spacing_m", "number_of_samples",
        "actual_mean_spacing_m", "actual_min_spacing_m", "actual_max_spacing_m", "train_speed_mps",
        "mean_temporal_interval_ms", "min_temporal_interval_ms", "max_temporal_interval_ms",
        "first_position", "last_position", "timestamp_strictly_increasing",
        "unnecessary_duplicate_samples", "same_start_as_25m", "same_end_as_25m",
        "baseline_vertices_preserved_in_order", "all_samples_on_baseline_polyline",
        "polyline_progress_nondecreasing", "max_deviation_from_baseline_polyline_m",
        "route_length_difference_from_25m_m", "same_polyline_geometry_as_25m",
    }
    trajectory_schema_ok = trajectory_required <= csv_columns(ROOT / "analysis" / "trajectory_resolution_validation.csv")
    trajectory_cases = {(row.get("scene"), float(row.get("requested_spacing_m", -1))) for row in trajectory}
    expected_trajectory_cases = {(scene, float(spacing)) for scene in SCENES for spacing in SPACINGS}
    trajectory_formula_ok = all(
        math.isclose(float(row["train_speed_mps"]), 350.0 / 3.6, rel_tol=0.0, abs_tol=1e-9)
        and math.isclose(
            float(row["mean_temporal_interval_ms"]),
            float(row["actual_mean_spacing_m"]) / float(row["train_speed_mps"]) * 1000.0,
            rel_tol=0.0, abs_tol=1e-9,
        )
        and math.isclose(
            float(row["min_temporal_interval_ms"]),
            float(row["actual_min_spacing_m"]) / float(row["train_speed_mps"]) * 1000.0,
            rel_tol=0.0, abs_tol=1e-9,
        )
        and math.isclose(
            float(row["max_temporal_interval_ms"]),
            float(row["actual_max_spacing_m"]) / float(row["train_speed_mps"]) * 1000.0,
            rel_tol=0.0, abs_tol=1e-9,
        )
        for row in trajectory
    )
    trajectory_ok = len(trajectory) == 6 and trajectory_schema_ok and trajectory_cases == expected_trajectory_cases and trajectory_formula_ok and all(
        row.get("same_start_as_25m", "").lower() == "true"
        and row.get("same_end_as_25m", "").lower() == "true"
        and row.get("timestamp_strictly_increasing", "").lower() == "true"
        and row.get("baseline_vertices_preserved_in_order", "").lower() == "true"
        and row.get("all_samples_on_baseline_polyline", "").lower() == "true"
        and row.get("polyline_progress_nondecreasing", "").lower() == "true"
        and row.get("same_polyline_geometry_as_25m", "").lower() == "true"
        and abs(float(row.get("route_length_difference_from_25m_m", "inf"))) <= 1e-6
        and float(row.get("max_deviation_from_baseline_polyline_m", "inf")) <= 1e-6
        and int(float(row.get("unnecessary_duplicate_samples", "-1"))) == 0
        # The 25-m row is the exact legacy trajectory (E6 contains a 26.04-m
        # segment); only inserted 5/2-m grids are required to obey a hard bound.
        and (float(row["requested_spacing_m"]) == 25.0
             or float(row["actual_max_spacing_m"]) <= float(row["requested_spacing_m"]) + 1e-3)
        for row in trajectory
    )
    add(checks, "six validated trajectories with identical ordered polyline geometry", "pass" if trajectory_ok else "fail", {
        "rows": len(trajectory), "schema": trajectory_schema_ok,
        "case_inventory": trajectory_cases == expected_trajectory_cases,
        "distance_over_speed_timestamps": trajectory_formula_ok,
    })

    experiment_manifest_path = ROOT / "experiment_manifest.json"
    experiment_manifest = json.loads(experiment_manifest_path.read_text(encoding="utf-8")) if experiment_manifest_path.exists() else {}
    config_controls: dict[str, dict[str, bool]] = {}
    for scene in SCENES:
        for spacing in SPACINGS:
            path = ROOT / "configs" / f"config_{scene}_{spacing}m.yaml"
            if not path.exists():
                config_controls[f"{scene}_{spacing}m"] = {"exists": False}
                continue
            config = yaml.safe_load(path.read_text(encoding="utf-8"))
            ray = config.get("ray_tracing", {})
            config_controls[f"{scene}_{spacing}m"] = {
                "exists": True,
                "only_requested_spacing": float(config.get("external_scene", {}).get("trajectory_spacing_m", -1)) == float(spacing),
                "speed_350_kmh": float(config.get("simulation", {}).get("train_speed_kmh", -1)) == 350.0,
                "carrier_30_ghz": float(config.get("simulation", {}).get("frequency_hz", -1)) == 30e9,
                "max_depth_6": int(ray.get("max_depth", -1)) == 6,
                "samples_per_source_2000": int(ray.get("samples_per_src", -1)) == 2000,
                "physics_switches": (
                    ray.get("enable_diffraction") is True
                    and ray.get("enable_diffuse_reflection") is True
                    and ray.get("enable_refraction") is False
                    and ray.get("require_sionna_backend") is True
                    and ray.get("fallback_on_empty_sionna_paths") is False
                ),
            }
    manifest_controls = {
        "resolutions": experiment_manifest.get("resolutions_m") == [25, 5, 2],
        "speed": float(experiment_manifest.get("train_speed_kmh", -1)) == 350.0,
        "carrier": float(experiment_manifest.get("carrier_frequency_hz", -1)) == 30e9,
        "a3_operating_points": experiment_manifest.get("a3_operating_points") == EXPECTED_A3,
        "outage_threshold": float(experiment_manifest.get("outage_threshold_db", math.nan)) == -6.0,
        "pingpong_window": float(experiment_manifest.get("pingpong_window_s", math.nan)) == 1.0,
        "measurement_polling": float(experiment_manifest.get("measurement_interval_ms_reported", math.nan)) == 50.0,
        "auxiliary_not_hacked": experiment_manifest.get("auxiliary_measurement_test") == "not_run_no_standards_consistent_configurable_cadence_found",
        "scene_mapping": all(
            experiment_manifest.get("scene_mapping", {}).get(scene, {}).get("scene_id") == SELECTED_SCENES[scene]["id"]
            for scene in SCENES
        ),
    }
    experiment_controls_ok = all(manifest_controls.values()) and len(config_controls) == 6 and all(
        all(values.values()) for values in config_controls.values()
    )
    add(checks, "fixed scientific controls and exact 18-case design contract", "pass" if experiment_controls_ok else "fail", {
        "manifest": manifest_controls, "configs": config_controls,
    })

    expected_command_cases = {
        f"{scene}_{spacing}m_{mode}": (scene, spacing, mode)
        for scene in SCENES for spacing in SPACINGS for mode in MODES
    }
    command_records: dict[str, dict] = {}
    command_failures: list[dict] = []
    for case_id, (scene, spacing, mode) in expected_command_cases.items():
        path = ROOT / "commands" / f"{case_id}.json"
        shell_path = ROOT / "commands" / f"{case_id}.sh"
        if not path.exists() or not shell_path.exists():
            command_failures.append({"case": case_id, "reason": "missing JSON or shell command record"})
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        command_records[case_id] = record
        command = record.get("command", [])
        shell_text = shell_path.read_text(encoding="utf-8")
        portable_shell = record.get("portable_shell", {})
        expected_point = EXPECTED_A3[mode]
        expected_args = {
            "--algo=FixedA3", "--channel=traces", "--speed=350.0",
            f"--HOM_base={float(expected_point['hom_db'])}",
            f"--TTT_base={float(expected_point['ttt_ms'])}",
            "--rngSeed=1", "--rngRun=1", "--numerology=3", "--beamPeriodMs=100",
            "--beamformingMethod=ns3::DirectPathBeamforming", "--useIdealRrc=1",
            "--bgUesPerCell=0", "--appIntervalUs=1000", "--appPacketSize=1200",
            "--fastEval=0", "--zmq_enabled=0",
        }
        checks_for_case = {
            "identity": (
                record.get("case_id") == case_id and record.get("scene") == scene
                and int(record.get("resolution_m", -1)) == spacing and record.get("mode") == mode
            ),
            "a3": (
                float(record.get("hom_db", math.nan)) == float(expected_point["hom_db"])
                and float(record.get("ttt_ms", math.nan)) == float(expected_point["ttt_ms"])
            ),
            "fixed_controls": (
                float(record.get("train_speed_kmh", math.nan)) == 350.0
                and float(record.get("measurement_controller_polling_ms", math.nan)) == 50.0
                and int(record.get("rng_seed", -1)) == 1 and int(record.get("rng_run", -1)) == 1
            ),
            "command_contract": isinstance(command, list) and expected_args <= set(command),
            "audited_executable": (
                record.get("ns3_version") == experiment_manifest.get("ns3_version")
                and record.get("fiveg_lena_version") == experiment_manifest.get("fiveg_lena_version")
                and record.get("ns3_git_commit") == experiment_manifest.get("ns3_git_commit")
                and record.get("program_source_sha256") == experiment_manifest.get("ns3_program_sha256")
                and record.get("binary_sha256") == experiment_manifest.get("ns3_binary_sha256")
                and int(record.get("ns3_shared_library_count", -1)) == int(experiment_manifest.get("ns3_shared_library_count", -2))
                and record.get("ns3_shared_library_aggregate_sha256") == experiment_manifest.get("ns3_shared_library_aggregate_sha256")
            ),
            "isolated_output": any(
                argument.startswith(
                    f"--outputDir={record.get('executor', {}).get('linux_experiment_root')}/ns3/{scene}/{spacing}m/{mode}"
                    if record.get("executor", {}).get("type") == "docker-desktop-wsl2"
                    else f"--outputDir={ROOT / 'ns3' / scene / f'{spacing}m' / mode}"
                )
                for argument in command
            ),
            "provenance_state": record.get("provenance_state") in {
                "complete inputs available", "dry-run plan; final input/output hashes pending",
            },
            "executor_contract": (
                record.get("executor", {}).get("type") == "native"
                or (
                    record.get("executor", {}).get("type") == "docker-desktop-wsl2"
                    and all(
                        record.get("executor", {}).get(key)
                        == experiment_manifest.get("local_wsl2_executor", {}).get(key)
                        for key in (
                            "type", "distro", "kernel", "loader_sha256",
                            "system_runtime_file_count", "system_runtime_aggregate_sha256",
                            "private_runtime_file_count", "private_runtime_aggregate_sha256",
                        )
                    )
                )
            ),
            "portable_linux_shell": (
                shell_text.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
                and "RT_SENSITIVITY_EXPERIMENT_ROOT" in shell_text
                and "SIOLENA_NS3_REPO_ROOT" in shell_text
                and 'exec "$BINARY"' in shell_text
                and f"--scene={record.get('scene_name', '')}" in shell_text
                and f"--tracesScenario={record.get('traces_scenario', '')}" in shell_text
                and f"--sceneConfig=$EXPERIMENT_ROOT/ns3_package/configs_runtime/{scene}_{spacing}m.json" in shell_text
                and f"--outputDir=$EXPERIMENT_ROOT/ns3/{scene}/{spacing}m/{mode}/raw" in shell_text
                and "--traceParent=$EXPERIMENT_ROOT/ns3_ready" in shell_text
                and not re.search(r"[A-Za-z]:\\", shell_text)
                and "/mnt/c/Users/" not in shell_text
                and portable_shell.get("path") == f"commands/{case_id}.sh"
                and portable_shell.get("sha256") == sha256(shell_path)
            ),
        }
        if not all(checks_for_case.values()):
            command_failures.append({"case": case_id, "checks": checks_for_case})
    command_plan_ok = len(command_records) == 18 and not command_failures
    command_inputs_final = command_plan_ok and all(
        record.get("provenance_state") == "complete inputs available" for record in command_records.values()
    )
    command_plan_status = (
        "fail" if not command_plan_ok
        else "pending" if fine_manifests_complete and not command_inputs_final
        else "pass"
    )
    add(checks, "materialized dry-run plan for all 18 isolated ns-3 cases", command_plan_status, {
        "records": len(command_records), "expected": 18, "failures": command_failures,
        "all_inputs_final": command_inputs_final,
        "provenance_states": sorted({record.get("provenance_state") for record in command_records.values()}),
    })

    physics: dict[str, set[str]] = {scene: set() for scene in SCENES}
    for scene in SCENES:
        for spacing in SPACINGS:
            path = ROOT / "sionna" / scene / f"{spacing}m" / "case_manifest.json"
            if path.exists():
                physics[scene].add(json.loads(path.read_text(encoding="utf-8"))["physics_hash"])
    physics_ok = all(len(values) == 1 for values in physics.values())
    add(checks, "physics hash invariant within each scene", "pass" if physics_ok else "fail", {key: sorted(value) for key, value in physics.items()})

    sionna_valid: list[str] = []
    sionna_pending: list[str] = []
    sionna_invalid: list[dict] = []
    for scene in SCENES:
        spec = SELECTED_SCENES[scene]
        baseline = PIPELINE_ROOT / spec["baseline"]
        source_inputs = {
            "baseline_config": PIPELINE_ROOT / "config" / spec["config"],
            "baseline_metadata": baseline / "scene_metadata.json",
            "scene_xml": baseline / "scene.xml",
        }
        for spacing in SPACINGS:
            case_id = f"{scene}_{spacing}m"
            case = ROOT / "sionna" / scene / f"{spacing}m"
            manifest_path = case / "case_manifest.json"
            metadata_path = case / "scene_metadata.json"
            config_path = ROOT / "configs" / f"config_{scene}_{spacing}m.yaml"
            if not all(path.exists() for path in (manifest_path, metadata_path, config_path)):
                sionna_invalid.append({"case": case_id, "reason": "missing case manifest, metadata or config"})
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            base_checks = {
                "config_path": Path(manifest.get("config", "")) == config_path,
                "config_hash": manifest.get("config_hash") == sha256(config_path),
                "physics_hash": manifest.get("physics_hash") == canonical_hash(physics_subset(config)),
                "scene_id": manifest.get("scene_id") == spec["id"],
                "resolution": float(manifest.get("resolution_m", -1)) == float(spacing),
                "gnb_count": int(manifest.get("gNB_count", -1)) == len(metadata.get("all_gnb_positions_m", [])),
                "trajectory_count": int(manifest.get("trajectory_sample_count", -1)) == len(metadata.get("rx_trajectory_samples", [])),
                "input_hashes": all(
                    path.exists() and manifest.get("input_file_hashes", {}).get(name) == sha256(path)
                    for name, path in source_inputs.items()
                ),
            }
            finalized = spacing == 25 or (case / "trace_manifest.json").exists()
            if not all(base_checks.values()):
                sionna_invalid.append({"case": case_id, "checks": base_checks})
                continue
            if not finalized:
                sionna_pending.append(case_id)
                continue
            output_root = baseline if spacing == 25 else case
            output_files = [
                *sorted(output_root.glob("mpc_gnb_*.csv")),
                output_root / "scene_metadata.json",
                output_root / "trace_manifest.json",
            ]
            expected_gnbs = int(manifest["gNB_count"])
            output_hashes = manifest.get("output_file_hashes", {})
            output_checks = {
                "status": manifest.get("status") in {"complete", "reused_legacy_baseline_complete"},
                "gnb_files": len(output_files) - 2 == expected_gnbs,
                "output_files_present": all(path.exists() for path in output_files),
                "output_hash_inventory": set(output_hashes) == {path.name for path in output_files},
                "output_hashes": all(path.exists() and output_hashes.get(path.name) == sha256(path) for path in output_files),
                "execution_provenance": spacing == 25 or (
                    manifest.get("exit_code") == 0
                    and finite_number(manifest.get("runtime_s")) and float(manifest["runtime_s"]) > 0
                    and isinstance(manifest.get("command_used"), list) and bool(manifest.get("command_used"))
                ),
            }
            if all(output_checks.values()):
                sionna_valid.append(case_id)
            else:
                sionna_invalid.append({"case": case_id, "checks": output_checks})
    sionna_status = "pass" if len(sionna_valid) == 6 else ("fail" if sionna_invalid else "pending")
    add(checks, "six cryptographically verified Sionna case manifests", sionna_status, {
        "valid": sionna_valid, "pending": sionna_pending, "invalid": sionna_invalid,
    })

    lock_path = ROOT / "baseline_integrity.json"
    baseline_mismatches = []
    if lock_path.exists():
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        for scene, record in lock["scenes"].items():
            source = Path(record["source_directory"])
            for name, expected in record["files"].items():
                path = source / name
                if not path.exists() or path.stat().st_size != expected["size"] or sha256(path) != expected["sha256"]:
                    baseline_mismatches.append(f"{scene}/{name}")
    add(checks, "baseline source integrity lock", "pass" if lock_path.exists() and not baseline_mismatches else "fail", {"lock": str(lock_path), "mismatches": baseline_mismatches})

    subprocess.run([sys.executable, str(ROOT / "validate_rt_traces.py")], check=True)
    rt_rows = read_csv(ROOT / "analysis" / "rt_trace_validation.csv")
    rt_notes = (ROOT / "analysis" / "rt_trace_validation.md").read_text(encoding="utf-8")
    complete_networks = re.findall(r"(E[26]) (25|5|2)m: expected=(\d+), network_union=(\d+), .* missing_network=(\d+)", rt_notes)
    numeric_ok = all(
        int(float(row["num_invalid_values"])) == 0
        and int(float(row["nan_count"])) == 0
        and int(float(row["inf_count"])) == 0
        and finite_number(row.get("delay_min_s"))
        and float(row["delay_min_s"]) >= 0.0
        and finite_number(row.get("mean_mpc_count"))
        and finite_number(row.get("p5_mpc_count"))
        and finite_number(row.get("p50_mpc_count"))
        and finite_number(row.get("p95_mpc_count"))
        and finite_number(row.get("doppler_min_hz"))
        and finite_number(row.get("doppler_max_hz"))
        and max(abs(float(row["doppler_min_hz"])), abs(float(row["doppler_max_hz"]))) <= 9800.0
        for row in rt_rows
    )
    # Fine sampling can expose trajectory locations where every link has zero
    # rays. These are complete no-path observations, not missing computation;
    # the handoff converter retains them as weak-path outage sentinels.
    network_ok = len(complete_networks) == 6 and all(
        int(expected) == int(union) + int(missing)
        for _, _, expected, union, missing in complete_networks
    )
    rt_validation_ok = len(rt_rows) == 60 and numeric_ok and network_ok
    rt_validation_status = "pass" if rt_validation_ok else ("fail" if fine_manifests_complete or len(rt_rows) >= 60 else "pending")
    add(checks, "complete RT timestamp/Doppler/MPC/numeric validation", rt_validation_status, {
        "station_rows": len(rt_rows), "expected_station_rows": 60,
        "complete_network_cases": len(complete_networks), "numeric_checks_pass": numeric_ok,
    })

    readiness_path = ROOT / "ns3_package" / "readiness.json"
    readiness = json.loads(readiness_path.read_text(encoding="utf-8")) if readiness_path.exists() else {}
    ready_count = int(readiness.get("ready_case_count", 0))
    raw_status = "pass" if ready_count == 6 else ("fail" if fine_manifests_complete else "pending")
    add(checks, "six validated raw MPC trace sets", raw_status, {"ready": ready_count, "expected": 6})
    converted = []
    for scene in SCENES:
        metadata = json.loads((ROOT / "sionna" / scene / "25m" / "scene_metadata.json").read_text(encoding="utf-8"))
        expected_gnbs = len(metadata["all_gnb_positions_m"])
        for spacing in SPACINGS:
            scenario = ROOT / "ns3_ready" / f"RTSensitivity_{scene}_{spacing}m"
            summary = scenario / "conversion_summary.json"
            parameter = scenario / "Input" / "paraCfgCurrent.txt"
            if summary.exists() and parameter.exists():
                data = json.loads(summary.read_text(encoding="utf-8"))
                if int(data.get("num_gnbs", -1)) == expected_gnbs:
                    converted.append(f"{scene}_{spacing}m")
    handoff_check = None
    if len(converted) == 6:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "ns3_package" / "verify_handoff.py"), "--experiment-root", str(ROOT)],
            cwd=ROOT, capture_output=True, text=True,
        )
        handoff_check = {"exit_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}
    conversion_ok = len(converted) == 6 and handoff_check is not None and handoff_check["exit_code"] == 0
    conversion_status = "pass" if conversion_ok else ("fail" if fine_manifests_complete or len(converted) >= 6 else "pending")
    add(checks, "six authoritative ns3-ready conversions with transfer checksums", conversion_status, {
        "converted": converted, "handoff_integrity": handoff_check,
    })

    ns3_complete = []
    ns3_failed_attempts = []
    ns3_invalid = []
    for scene in SCENES:
        for spacing in SPACINGS:
            for mode in MODES:
                case = ROOT / "ns3" / scene / f"{spacing}m" / mode
                kpi_path = case / "kpi.json"
                exit_path = case / "exit_code.txt"
                if kpi_path.exists() and exit_path.exists() and exit_path.read_text().strip() == "0":
                    kpi = json.loads(kpi_path.read_text(encoding="utf-8"))
                    event_path = case / "handover_events.csv"
                    events = read_csv(event_path)
                    metadata_path = case / "case_metadata.json"
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
                    kpi_required = {
                        "mean_sinr_db", "p5_sinr_db", "radio_outage_ratio_pct", "handover_count",
                        "pingpong_count", "handover_per_km", "pingpong_per_km", "num_valid_snapshots",
                        "trace_hash", "runtime_s", "measurement_interval_ms", "seed",
                    }
                    event_columns = {
                        "scene", "resolution_m", "operating_point", "event_index", "handover_start_time_s",
                        "handover_end_time_s", "source_gnb", "target_gnb", "train_position_m", "train_x",
                        "train_y", "SINR_before", "SINR_after", "event_source", "context_join",
                        "start_event_join",
                    }
                    event_ok = event_columns <= csv_columns(event_path) and all(
                        row.get("event_source") == "NrGnbRrc/HandoverEndOk"
                        and row.get("start_event_join") in {
                            "exact IMSI/source/target/time match",
                            "unavailable: no exact start match",
                        }
                        and (
                            row.get("start_event_join") != "exact IMSI/source/target/time match"
                            or (
                                finite_number(row.get("handover_start_time_s"))
                                and finite_number(row.get("handover_end_time_s"))
                                and float(row["handover_start_time_s"]) <= float(row["handover_end_time_s"])
                            )
                        )
                        for row in events
                    )
                    metadata_keys_ok = CASE_METADATA_REQUIRED <= set(metadata)
                    expected_point = EXPECTED_A3[mode]
                    expected_command_args = {
                        "--algo=FixedA3", "--channel=traces", "--speed=350.0",
                        f"--HOM_base={float(expected_point['hom_db'])}",
                        f"--TTT_base={float(expected_point['ttt_ms'])}",
                        "--rngSeed=1", "--rngRun=1", "--numerology=3", "--beamPeriodMs=100",
                        "--beamformingMethod=ns3::DirectPathBeamforming", "--useIdealRrc=1",
                        "--bgUesPerCell=0", "--appIntervalUs=1000", "--appPacketSize=1200",
                        "--fastEval=0", "--zmq_enabled=0",
                    }
                    metadata_values_ok = (
                        metadata.get("exit_code") == 0
                        and metadata.get("case_id") == f"{scene}_{spacing}m_{mode}"
                        and metadata.get("scene") == scene and int(metadata.get("resolution_m", -1)) == spacing
                        and metadata.get("mode") == mode
                        and float(metadata.get("hom_db", math.nan)) == float(expected_point["hom_db"])
                        and float(metadata.get("ttt_ms", math.nan)) == float(expected_point["ttt_ms"])
                        and float(metadata.get("train_speed_kmh", math.nan)) == 350.0
                        and float(metadata.get("carrier_frequency_hz", math.nan)) == 30e9
                        and float(metadata.get("measurement_controller_polling_ms", math.nan)) == 50.0
                        and float(metadata.get("warmup_exclusion_s", math.nan)) == 0.15
                        and int(metadata.get("rng_seed", -1)) == 1 and int(metadata.get("rng_run", -1)) == 1
                        and int(metadata.get("rt_seed", -1)) == 42
                        and isinstance(metadata.get("command"), list) and bool(metadata.get("command"))
                        and expected_command_args <= set(metadata.get("command", []))
                        and isinstance(metadata.get("host"), dict) and bool(metadata.get("host"))
                        and isinstance(metadata.get("output_file_hashes"), dict) and bool(metadata.get("output_file_hashes"))
                        and metadata.get("finished_utc")
                        and float(kpi.get("hom_db", math.nan)) == float(expected_point["hom_db"])
                        and float(kpi.get("ttt_ms", math.nan)) == float(expected_point["ttt_ms"])
                        and float(kpi.get("measurement_interval_ms", math.nan)) == 50.0
                        and int(kpi.get("seed", -1)) == 1 and int(kpi.get("rng_run", -1)) == 1
                    )
                    output_hashes_ok = metadata_values_ok and all(
                        (case / relative).exists() and sha256(case / relative) == expected
                        for relative, expected in metadata.get("output_file_hashes", {}).items()
                    )
                    provenance_checks = ns3_provenance_checks(ROOT, scene, spacing, metadata, experiment_manifest)
                    provenance_hashes_ok = all(provenance_checks.values())
                    complete_case = (
                        kpi_required <= set(kpi) and event_ok and len(events) == int(kpi["handover_count"])
                        and metadata_keys_ok and metadata_values_ok and output_hashes_ok and provenance_hashes_ok
                    )
                    if complete_case:
                        ns3_complete.append(f"{scene}_{spacing}m_{mode}")
                    else:
                        ns3_invalid.append({
                            "case": f"{scene}_{spacing}m_{mode}", "kpi_schema": kpi_required <= set(kpi),
                            "event_schema_and_source": event_ok, "event_count": len(events),
                            "expected_event_count": int(kpi.get("handover_count", -1)),
                            "metadata_schema": metadata_keys_ok, "metadata_values": metadata_values_ok,
                            "output_hashes": output_hashes_ok, "provenance": provenance_checks,
                        })
                elif exit_path.exists():
                    ns3_failed_attempts.append({"case": f"{scene}_{spacing}m_{mode}", "exit": exit_path.read_text().strip()})
    ns3_status = "pass" if len(ns3_complete) == 18 else ("fail" if len(ns3_complete) + len(ns3_invalid) == 18 else "pending")
    add(checks, "18 complete normalized ns-3 cases with per-case provenance", ns3_status, {
        "complete": len(ns3_complete), "invalid": ns3_invalid, "failed_attempts_not_counted": ns3_failed_attempts,
    })

    analysis_regenerated = False
    if len(ns3_complete) == 18:
        # Regenerate every analysis/publication artifact from the just-verified
        # cases so a stale CSV, figure or prose file cannot satisfy completion.
        subprocess.run([sys.executable, str(ROOT / "analyze_results.py")], cwd=ROOT, check=True)
        analysis_regenerated = True

    analysis_required = [
        "analysis/all_cases_raw.csv", "analysis/resolution_sensitivity_summary.csv",
        "analysis/operating_point_rankings.csv", "analysis/handover_events.csv",
        "analysis/handover_event_alignment.csv",
    ]
    raw_rows = read_csv(ROOT / analysis_required[0])
    summary_rows = read_csv(ROOT / analysis_required[1])
    ranking_rows = read_csv(ROOT / analysis_required[2])
    event_rows = read_csv(ROOT / analysis_required[3])
    alignment_rows = read_csv(ROOT / analysis_required[4])
    expected_cases = {(scene, str(spacing), mode) for scene in SCENES for spacing in SPACINGS for mode in MODES}
    actual_cases = {(row.get("scene"), row.get("resolution_m"), row.get("a3_mode")) for row in raw_rows}
    summary_required = {
        "scene", "a3_mode", "delta_outage_25m_vs_2m_pct_points", "relative_outage_error_25m_vs_2m_pct",
        "delta_ho_25m_vs_2m", "delta_pp_25m_vs_2m", "delta_outage_5m_vs_2m_pct_points",
        "relative_outage_error_5m_vs_2m_pct", "delta_ho_5m_vs_2m", "delta_pp_5m_vs_2m",
    }
    ranking_required = {"scene", "resolution_m", "outage_best_to_worst", "handover_low_to_high", "pingpong_low_to_high"}
    alignment_required = {
        "scene", "operating_point", "comparison", "sequence_identical", "alignment_method",
        "ambiguous_repeated_transition_pairs_excluded", "matched_events",
        "extra_events", "missing_events", "mean_abs_HO_start_time_shift_ms",
        "median_abs_HO_start_time_shift_ms", "max_abs_HO_start_time_shift_ms",
        "mean_abs_HO_end_time_shift_ms", "median_abs_HO_end_time_shift_ms",
        "max_abs_HO_end_time_shift_ms", "mean_abs_HO_position_shift_m",
        "median_abs_HO_position_shift_m", "max_abs_HO_position_shift_m",
    }
    analysis_ok = (
        all((ROOT / name).exists() for name in analysis_required)
        and len(raw_rows) == 18 and actual_cases == expected_cases and KPI_REQUIRED <= csv_columns(ROOT / analysis_required[0])
        and len(summary_rows) == 6 and summary_required <= csv_columns(ROOT / analysis_required[1])
        and len(ranking_rows) == 6 and ranking_required <= csv_columns(ROOT / analysis_required[2])
        and EVENT_REQUIRED <= csv_columns(ROOT / analysis_required[3])
        and len(event_rows) == sum(int(float(row["handover_count"])) for row in raw_rows)
        and len(alignment_rows) == 12 and alignment_required <= csv_columns(ROOT / analysis_required[4])
    )
    analysis_status = "pass" if analysis_ok else ("pending" if len(ns3_complete) < 18 else "fail")
    add(checks, "complete analysis CSV suite with required schemas", analysis_status, {
        "raw_rows": len(raw_rows), "summary_rows": len(summary_rows), "ranking_rows": len(ranking_rows),
        "event_rows": len(event_rows), "alignment_rows": len(alignment_rows),
        "regenerated_from_18_verified_cases": analysis_regenerated,
    })

    publication_required = [
        "figures/fig_resolution_outage.pdf", "figures/fig_resolution_outage.png",
        "figures/fig_resolution_handover_density.pdf", "figures/fig_resolution_handover_density.png",
        "tables/table_temporal_resolution_sensitivity.csv", "tables/table_temporal_resolution_sensitivity.tex",
        "paper_ready/result_interpretation.md",
        "paper_ready/results_temporal_resolution.md", "paper_ready/revised_limitations.md",
        "paper_ready/revised_contribution.md", "paper_ready/revised_conclusion_sentence.md",
        "paper_ready/final_technical_assessment.md",
    ]
    missing_publication = [name for name in publication_required if not (ROOT / name).exists() or (ROOT / name).stat().st_size == 0]
    table_rows = read_csv(ROOT / "tables" / "table_temporal_resolution_sensitivity.csv")
    table_columns = csv_columns(ROOT / "tables" / "table_temporal_resolution_sensitivity.csv")
    expected_table_columns = {"Scene", "A3 mode"} | {
        f"{metric} {spacing}m" for metric in ("Outage", "HO", "PP") for spacing in SPACINGS
    }
    interpretation_path = ROOT / "paper_ready" / "result_interpretation.md"
    interpretation = interpretation_path.read_text(encoding="utf-8") if interpretation_path.exists() else ""
    results_text = (ROOT / "paper_ready" / "results_temporal_resolution.md").read_text(encoding="utf-8") if (ROOT / "paper_ready" / "results_temporal_resolution.md").exists() else ""
    limitations_text = (ROOT / "paper_ready" / "revised_limitations.md").read_text(encoding="utf-8") if (ROOT / "paper_ready" / "revised_limitations.md").exists() else ""
    contribution_text = (ROOT / "paper_ready" / "revised_contribution.md").read_text(encoding="utf-8") if (ROOT / "paper_ready" / "revised_contribution.md").exists() else ""
    conclusion_text = (ROOT / "paper_ready" / "revised_conclusion_sentence.md").read_text(encoding="utf-8") if (ROOT / "paper_ready" / "revised_conclusion_sentence.md").exists() else ""
    final_assessment = (ROOT / "paper_ready" / "final_technical_assessment.md").read_text(encoding="utf-8") if (ROOT / "paper_ready" / "final_technical_assessment.md").exists() else ""
    result_texts = (interpretation, results_text, limitations_text, contribution_text, conclusion_text, final_assessment)
    no_placeholders = all(not re.search(r"\b(?:TBD|TODO|placeholder)\b|\[[^\]]*(?:value|result)[^\]]*\]", text, re.IGNORECASE) for text in result_texts)
    content_checks = {
        "interpretation_classification": "Classification:" in interpretation,
        "all_ranking_types_reported": "All outage/HO/PP ranking comparisons preserved:" in interpretation,
        "global_claim_reported": "Cross-site no-uniformly-preferable operating-point claim at 2 m:" in interpretation,
        "robustness_quantified": all(token in interpretation for token in (
            "Maximum absolute outage change:", "Median absolute outage change:",
            "Maximum HO-count change:", "Maximum PP-count change:",
            "Identical completed-HO event sequences:", "Outage step magnitude decreased",
        )),
        "no_arbitrary_small_change_threshold": "No numerical small-change threshold is imposed" in interpretation,
        "ambiguous_event_matches_disclosed": all(
            "repeated-transition pairs" in text for text in (interpretation, results_text, final_assessment)
        ),
        "results_from_complete_matrix": "complete 18-case sensitivity matrix" in results_text,
        "results_quantify_fine_reference": "relative to the 2-m reference" in results_text,
        "measurement_limitation_preserved": all(token in limitations_text for token in ("40-ms TTT", "50-ms", "joint HOM–TTT")),
        "no_fully_eliminated_limitation_claim": "fully eliminated" not in limitations_text.lower(),
        "contribution_nonempty": bool(contribution_text.strip()),
        "contribution_avoids_prohibited_overclaim": not re.search(
            r"\b(?:prove|guarantee|optimal|universally robust)\b", contribution_text, re.IGNORECASE
        ),
        "conclusion_nonempty": bool(conclusion_text.strip()),
        "final_assessment_A_to_J": all(f"## {letter}." in final_assessment for letter in "ABCDEFGHIJ"),
        "final_assessment_direct_answer": "Does the main paper conclusion survive RT refinement?" in final_assessment,
        "no_placeholders": no_placeholders,
    }
    png_quality = {}
    for name in ("figures/fig_resolution_outage.png", "figures/fig_resolution_handover_density.png"):
        path = ROOT / name
        if not path.exists():
            continue
        try:
            from PIL import Image
            with Image.open(path) as image:
                dpi = image.info.get("dpi", (0.0, 0.0))
                png_quality[name] = {"size_px": list(image.size), "dpi": list(dpi), "pass": min(dpi) >= 299.0 and min(image.size) >= 1000}
        except Exception as error:
            png_quality[name] = {"pass": False, "error": str(error)}
    publication_ok = (
        not missing_publication and len(table_rows) == 6 and expected_table_columns <= table_columns
        and all(content_checks.values())
        and all(value.get("pass") for value in png_quality.values()) and len(png_quality) == 2
    )
    publication_status = "pass" if publication_ok else ("pending" if len(ns3_complete) < 18 else "fail")
    add(checks, "paper-ready figures, table, and result-dependent prose", publication_status, {
        "missing": missing_publication, "table_rows": len(table_rows), "table_schema": expected_table_columns <= table_columns,
        "content_checks": content_checks, "png_quality": png_quality,
    })

    reproducibility_required = [
        "experiment_manifest.json", "baseline_integrity.json", "audit.md", "README.md",
        "analysis/implementation_inventory.md", "analysis/requirements_traceability.md",
        "UBUNTU_NS3_RUN_INSTRUCTIONS.md", "run_experiment.py", "prepare_ns3_package.py",
        "post_rt_watcher.py", "wsl2_matrix_watcher.py", "wsl2_bridge_config.json",
        "checkpoint_rt_station.py", "station_checkpoint_watcher.py",
        "test_ns3_parser.py", "test_verifier_provenance.py", "test_wsl2_bridge_preflight.py",
        "test_station_checkpoint_watcher.py",
        "ns3_package/run_resolution_matrix.py",
        "ns3_package/verify_handoff.py", "validate_rt_traces.py", "analyze_results.py",
        "paper_ready/methodology_temporal_resolution.md", "paper_ready/measurement_cadence_note.md",
        "paper_ready/trace_replay_note.md",
    ]
    missing_repro = [name for name in reproducibility_required if not (ROOT / name).exists()]
    regression_path = ROOT / "analysis" / "ns3_parser_regression.json"
    regression = json.loads(regression_path.read_text(encoding="utf-8")) if regression_path.exists() else {}
    provenance_regression_path = ROOT / "analysis" / "verifier_provenance_regression.json"
    provenance_regression = json.loads(provenance_regression_path.read_text(encoding="utf-8")) if provenance_regression_path.exists() else {}
    bridge_regression_path = ROOT / "analysis" / "wsl2_bridge_preflight.json"
    bridge_regression = json.loads(bridge_regression_path.read_text(encoding="utf-8")) if bridge_regression_path.exists() else {}
    station_regression_path = ROOT / "analysis" / "station_checkpoint_watcher_regression.json"
    station_regression = json.loads(station_regression_path.read_text(encoding="utf-8")) if station_regression_path.exists() else {}
    parser_expected_hashes = {
        "test_ns3_parser.py": sha256(ROOT / "test_ns3_parser.py") if (ROOT / "test_ns3_parser.py").exists() else None,
        "ns3_package/run_resolution_matrix.py": sha256(ROOT / "ns3_package" / "run_resolution_matrix.py") if (ROOT / "ns3_package" / "run_resolution_matrix.py").exists() else None,
        "analyze_results.py": sha256(ROOT / "analyze_results.py") if (ROOT / "analyze_results.py").exists() else None,
    }
    provenance_expected_hashes = {
        "test_verifier_provenance.py": sha256(ROOT / "test_verifier_provenance.py") if (ROOT / "test_verifier_provenance.py").exists() else None,
        "verify_experiment.py": sha256(ROOT / "verify_experiment.py") if (ROOT / "verify_experiment.py").exists() else None,
    }
    bridge_expected_hashes = {
        "test_wsl2_bridge_preflight.py": sha256(ROOT / "test_wsl2_bridge_preflight.py") if (ROOT / "test_wsl2_bridge_preflight.py").exists() else None,
        "ns3_package/run_resolution_matrix.py": sha256(ROOT / "ns3_package" / "run_resolution_matrix.py") if (ROOT / "ns3_package" / "run_resolution_matrix.py").exists() else None,
        "wsl2_bridge_config.json": sha256(ROOT / "wsl2_bridge_config.json") if (ROOT / "wsl2_bridge_config.json").exists() else None,
        "experiment_manifest.json": sha256(ROOT / "experiment_manifest.json") if (ROOT / "experiment_manifest.json").exists() else None,
        "wsl2_matrix_watcher.py": sha256(ROOT / "wsl2_matrix_watcher.py") if (ROOT / "wsl2_matrix_watcher.py").exists() else None,
    }
    station_expected_hashes = {
        "test_station_checkpoint_watcher.py": sha256(ROOT / "test_station_checkpoint_watcher.py") if (ROOT / "test_station_checkpoint_watcher.py").exists() else None,
        "station_checkpoint_watcher.py": sha256(ROOT / "station_checkpoint_watcher.py") if (ROOT / "station_checkpoint_watcher.py").exists() else None,
        "checkpoint_rt_station.py": sha256(ROOT / "checkpoint_rt_station.py") if (ROOT / "checkpoint_rt_station.py").exists() else None,
    }
    parser_regression_fresh = regression.get("tested_code_sha256") == parser_expected_hashes
    provenance_regression_fresh = provenance_regression.get("tested_code_sha256") == provenance_expected_hashes
    bridge_regression_fresh = bridge_regression.get("tested_code_sha256") == bridge_expected_hashes
    station_regression_fresh = station_regression.get("tested_code_sha256") == station_expected_hashes
    reproducibility_ok = (
        not missing_repro and regression.get("pass") is True
        and provenance_regression.get("pass") is True
        and bridge_regression.get("pass") is True
        and station_regression.get("pass") is True
        and parser_regression_fresh and provenance_regression_fresh and bridge_regression_fresh
        and station_regression_fresh
    )
    add(checks, "reproducibility, methodology, and real-raw parser regression", "pass" if reproducibility_ok else "fail", {
        "missing": missing_repro, "parser_regression_pass": regression.get("pass"),
        "verifier_provenance_regression_pass": provenance_regression.get("pass"),
        "wsl2_bridge_preflight_pass": bridge_regression.get("pass"),
        "station_checkpoint_watcher_regression_pass": station_regression.get("pass"),
        "parser_regression_fresh": parser_regression_fresh,
        "verifier_provenance_regression_fresh": provenance_regression_fresh,
        "wsl2_bridge_preflight_fresh": bridge_regression_fresh,
        "station_checkpoint_watcher_regression_fresh": station_regression_fresh,
    })

    complete = all(check["status"] == "pass" for check in checks)
    report = {
        "verified_utc": datetime.now(timezone.utc).isoformat(),
        "complete": complete,
        "counts": {
            "pass": sum(check["status"] == "pass" for check in checks),
            "pending": sum(check["status"] == "pending" for check in checks),
            "fail": sum(check["status"] == "fail" for check in checks),
        },
        "checks": checks,
    }
    output = ROOT / "analysis" / "completion_audit.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = ["# Completion audit", "", f"Complete: **{complete}**", ""]
    lines.extend(f"- [{check['status'].upper()}] {check['name']}: `{json.dumps(check['evidence'], ensure_ascii=False)}`" for check in checks)
    (ROOT / "analysis" / "completion_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if complete or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
