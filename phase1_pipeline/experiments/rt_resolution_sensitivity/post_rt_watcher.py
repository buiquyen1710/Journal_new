from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FINE_CASES = (("E2", 5), ("E2", 2), ("E6", 5), ("E6", 2))
STILL_ACTIVE = 259
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def process_active(pid: int) -> bool:
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def manifests() -> dict[str, bool]:
    return {
        f"{scene}_{spacing}m": (ROOT / "sionna" / scene / f"{spacing}m" / "trace_manifest.json").exists()
        for scene, spacing in FINE_CASES
    }


def write_status(payload: dict) -> None:
    path = ROOT / "logs" / "post_rt_watcher_status.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def run_stage(command: list[str], name: str) -> None:
    print(f"[{utc_now()}] {name}: {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Wait for fine RT traces, then validate and convert them without accepting partial CSVs.")
    parser.add_argument("--controller-pid", type=int, required=True)
    parser.add_argument("--poll-seconds", type=float, default=300.0)
    args = parser.parse_args()
    (ROOT / "logs").mkdir(parents=True, exist_ok=True)
    (ROOT / "logs" / "post_rt_watcher.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
    started = utc_now()
    while True:
        present = manifests()
        active = process_active(args.controller_pid)
        status = {
            "started_utc": started,
            "updated_utc": utc_now(),
            "watcher_pid": os.getpid(),
            "controller_pid": args.controller_pid,
            "controller_active": active,
            "fine_trace_manifests": present,
            "state": "waiting",
        }
        write_status(status)
        if all(present.values()):
            break
        if not active:
            status.update({"state": "failed", "reason": "controller exited before all four fine trace manifests existed"})
            write_status(status)
            print(status["reason"], file=sys.stderr, flush=True)
            return 2
        time.sleep(max(30.0, args.poll_seconds))

    try:
        write_status({**status, "updated_utc": utc_now(), "state": "validating"})
        run_stage([sys.executable, str(ROOT / "validate_rt_traces.py")], "validate_rt_traces")
        write_status({**status, "updated_utc": utc_now(), "state": "converting"})
        run_stage([sys.executable, str(ROOT / "prepare_ns3_package.py"), "--require-complete"], "prepare_ns3_package")
        write_status({**status, "updated_utc": utc_now(), "state": "verifying_handoff"})
        run_stage([
            sys.executable, str(ROOT / "ns3_package" / "verify_handoff.py"),
            "--experiment-root", str(ROOT),
        ], "verify_handoff")
        write_status({**status, "updated_utc": utc_now(), "state": "materializing_ns3_commands"})
        run_stage([
            sys.executable, str(ROOT / "run_experiment.py"),
            "--stage", "ns3", "--dry-run",
        ], "materialize_ns3_commands")
        write_status({**status, "updated_utc": utc_now(), "state": "auditing"})
        run_stage([sys.executable, str(ROOT / "verify_experiment.py")], "verify_experiment")
    except subprocess.CalledProcessError as error:
        write_status({**status, "updated_utc": utc_now(), "state": "failed", "reason": str(error)})
        raise
    write_status({
        **status,
        "updated_utc": utc_now(),
        "state": "complete",
        "result": "all fine RT traces validated and all six trace sets converted; ns-3/analysis gates may remain pending",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
