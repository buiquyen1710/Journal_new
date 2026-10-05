#!/usr/bin/env python3
"""Run exactly the three approved dense-E2 FixedA3 operating points."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
EXPECTED_HEAD = "cc25f66bfd2a0b27d1354a46da7796dadc93f5c9"
EXPECTED_BINARY_SHA256 = "d1e1cd48a5a02b3d386b8501676064d9508c0748c657bf778d6dbf8b898303b5"
BINARY = ROOT / "build/scratch/railway-digital-twin-evaluation/ns3.44-railway-digital-twin-evaluation-default"
SCENE_CONFIG = ROOT / "results_21_6/configs/Cau_Long_Bien.json"
TRACE_ROOT = ROOT / "experiments/rt_resolution_sensitivity/ns3_ready"
TRACE_SCENARIO = "RTSensitivity_E2_dense1923m_shadow_881"
TRACE_DIR = TRACE_ROOT / TRACE_SCENARIO
RESULT_ROOT = ROOT / "experiments/rt_resolution_sensitivity/results_dense1923m"
DEFINITION_ROOT = ROOT / "experiments/rt_resolution_sensitivity/run_definitions"
DEFINITIONS = [
    DEFINITION_ROOT / "E2_dense1923m_aggressive.json",
    DEFINITION_ROOT / "E2_dense1923m_balanced.json",
    DEFINITION_ROOT / "E2_dense1923m_conservative.json",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_trace_parameters() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (TRACE_DIR / "Input/paraCfgCurrent.txt").read_text(encoding="utf-8").splitlines():
        fields = line.split()
        values[fields[0]] = fields[-1]
    return values


def channel_block_counts(path: Path) -> list[int]:
    lines = path.read_text(encoding="utf-8").splitlines()
    blocks: list[int] = []
    cursor = 0
    while cursor < len(lines):
        paths = int(lines[cursor])
        blocks.append(paths)
        cursor += 1 if paths == 0 else 9
    return blocks


def validate_common() -> tuple[dict, dict[str, str], list[dict]]:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if head != EXPECTED_HEAD:
        raise RuntimeError(f"revision mismatch: {head} != {EXPECTED_HEAD}")
    if sha256(BINARY) != EXPECTED_BINARY_SHA256:
        raise RuntimeError("paper executable SHA-256 mismatch")
    scene = json.loads(SCENE_CONFIG.read_text(encoding="utf-8"))
    trace = read_trace_parameters()
    if int(trace["numberOfTimeDivisions"]) != 881:
        raise RuntimeError("dense trace does not contain 881 time divisions")
    channels = sorted((TRACE_DIR / "Output/Ns3/Channel").glob("Tx*Rx*.txt"))
    if len(channels) != 6:
        raise RuntimeError(f"dense trace has {len(channels)} channel files, expected 6")
    zero_indices = [478, 479, 573, 574, 627, 628, 664, 683, 684]
    for path in channels:
        counts = channel_block_counts(path)
        if len(counts) != 881 or any(counts[index] != 0 for index in zero_indices):
            raise RuntimeError(f"dense trace audit failed for {path}")
    definitions = [json.loads(path.read_text(encoding="utf-8")) for path in DEFINITIONS]
    expected = [(1.0, 40.0), (3.0, 160.0), (5.0, 320.0)]
    if [(case["hom_db"], case["ttt_ms"]) for case in definitions] != expected:
        raise RuntimeError("run definitions are not the approved three operating points")
    return scene, trace, definitions


def command_for(case: dict, output_dir: Path, scene: dict) -> list[str]:
    return [
        str(BINARY),
        "--scene=Cau_Long_Bien",
        "--algo=FixedA3",
        f"--sceneConfig={SCENE_CONFIG}",
        f"--outputDir={output_dir / 'raw'}",
        f"--traceParent={TRACE_ROOT}",
        f"--tracesScenario={TRACE_SCENARIO}",
        "--channel=traces",
        "--speed=350.0",
        f"--simTime={scene['simulation_time']}",
        f"--HOM_base={case['hom_db']}",
        f"--TTT_base={case['ttt_ms']}",
        "--rngSeed=1",
        "--rngRun=1",
        "--numerology=3",
        "--beamPeriodMs=100",
        "--beamformingMethod=ns3::DirectPathBeamforming",
        "--useIdealRrc=1",
        "--bgUesPerCell=0",
        "--appIntervalUs=1000",
        "--appPacketSize=1200",
        "--fastEval=0",
        "--zmq_enabled=0",
    ]


def resolved(case: dict, scene: dict, trace: dict[str, str]) -> dict:
    divisions = int(trace["numberOfTimeDivisions"])
    duration = float(trace["totalTimeDuration"])
    output_dir = RESULT_ROOT / case["output_subdir"]
    return {
        "case_name": case["case_name"],
        "operating_point": case["operating_point"],
        "hom_db": case["hom_db"],
        "ttt_ms": case["ttt_ms"],
        "trace_root": str(TRACE_ROOT.resolve()),
        "trace_scenario": TRACE_SCENARIO,
        "number_of_time_divisions": divisions,
        "total_trace_duration_s": duration,
        "trace_update_period_ms": duration / (divisions - 1) * 1000.0,
        "route_length_m": scene["track_length_m"],
        "speed_kmh": 350.0,
        "rng_seed": 1,
        "rng_run": 1,
        "simulation_time_s": scene["simulation_time"],
        "output_directory": str(output_dir.resolve()),
        "scene_config": str(SCENE_CONFIG.resolve()),
        "paper_executable": str(BINARY.resolve()),
        "paper_executable_sha256": EXPECTED_BINARY_SHA256,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    scene, trace, definitions = validate_common()
    for case in definitions:
        info = resolved(case, scene, trace)
        print(json.dumps(info, indent=2), flush=True)
    if args.dry_run:
        return
    if RESULT_ROOT.exists():
        raise FileExistsError(f"refusing to overwrite existing results root: {RESULT_ROOT}")
    RESULT_ROOT.mkdir(parents=True)
    for case in definitions:
        case_dir = RESULT_ROOT / case["output_subdir"]
        case_dir.mkdir()
        info = resolved(case, scene, trace)
        command = command_for(case, case_dir, scene)
        info["command"] = command
        info["started_at"] = datetime.now().astimezone().isoformat()
        (case_dir / "resolved_pre_run.json").write_text(
            json.dumps(info, indent=2) + "\n", encoding="utf-8"
        )
        (case_dir / "command.sh").write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\n" + " ".join(command) + "\n",
            encoding="utf-8",
        )
        started = time.monotonic()
        with (case_dir / "stdout.log").open("w", encoding="utf-8") as stdout, \
             (case_dir / "stderr.log").open("w", encoding="utf-8") as stderr:
            completed = subprocess.run(command, cwd=ROOT, stdout=stdout, stderr=stderr, check=False)
        elapsed = time.monotonic() - started
        (case_dir / "exit_code.txt").write_text(f"{completed.returncode}\n", encoding="utf-8")
        (case_dir / "wall_time_s.txt").write_text(f"{elapsed:.6f}\n", encoding="utf-8")
        info["finished_at"] = datetime.now().astimezone().isoformat()
        info["exit_code"] = completed.returncode
        info["wall_time_s"] = elapsed
        (case_dir / "run_metadata.json").write_text(
            json.dumps(info, indent=2) + "\n", encoding="utf-8"
        )
        print(
            f"COMPLETED {case['case_name']} exit={completed.returncode} wall_time_s={elapsed:.3f}",
            flush=True,
        )
        if completed.returncode != 0:
            raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
