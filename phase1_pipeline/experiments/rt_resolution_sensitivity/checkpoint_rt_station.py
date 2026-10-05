from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path
from statistics import mean, median

from validate_rt_traces import SPEED_MPS, THEORETICAL_DOPPLER_HZ, percentile, trajectory_timestamps


ROOT = Path(__file__).resolve().parent
NUMERIC_FIELDS = ("delay_s", "amplitude_real", "amplitude_imag", "doppler_hz")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only checkpoint for one closed fine-RT station CSV.")
    parser.add_argument("--scene", choices=("E2", "E6"), required=True)
    parser.add_argument("--resolution", type=int, choices=(5, 2), required=True)
    parser.add_argument("--station", required=True, help="Station suffix such as gnb_b")
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    args = parser.parse_args()
    case = ROOT / "sionna" / args.scene / f"{args.resolution}m"
    csv_path = case / f"mpc_{args.station.lower()}.csv"
    metadata = json.loads((case / "scene_metadata.json").read_text(encoding="utf-8"))
    expected = set(trajectory_timestamps(metadata))
    rows = []
    invalid = nan_count = inf_count = duplicate_pairs = 0
    unexpected: set[int] = set()
    timestamps_in_file: list[int] = []
    pair_counts: Counter[tuple[int, int]] = Counter()
    delays: list[float] = []
    dopplers: list[float] = []
    gains: list[float] = []
    los_values: set[int] = set()
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp_ns", "path_id", "los_flag", *NUMERIC_FIELDS}
        schema_ok = required <= set(reader.fieldnames or [])
        for row in reader:
            rows.append(row)
            try:
                timestamp = int(row["timestamp_ns"])
                path_id = int(row["path_id"])
                los = int(float(row["los_flag"]))
                numeric = [float(row[key]) for key in NUMERIC_FIELDS]
            except (KeyError, TypeError, ValueError):
                invalid += 1
                continue
            nan_count += sum(math.isnan(value) for value in numeric)
            inf_count += sum(math.isinf(value) for value in numeric)
            if any(not math.isfinite(value) for value in numeric):
                invalid += 1
                continue
            timestamps_in_file.append(timestamp)
            pair_counts[(timestamp, path_id)] += 1
            unexpected.add(timestamp) if timestamp not in expected else None
            los_values.add(los)
            delays.append(numeric[0])
            dopplers.append(numeric[3])
            gains.append(20.0 * math.log10(max(math.hypot(numeric[1], numeric[2]), 1e-300)))
    duplicate_pairs = sum(count - 1 for count in pair_counts.values() if count > 1)
    observed = {timestamp for timestamp, _ in pair_counts}
    counts = Counter(timestamp for timestamp, _ in pair_counts)
    mpc_counts = list(counts.values())
    max_abs_doppler = max((abs(value) for value in dopplers), default=0.0)
    report = {
        "scope": "closed-station checkpoint only; does not finalize the network case",
        "scene": args.scene,
        "resolution_m": args.resolution,
        "station": csv_path.stem,
        "csv": str(csv_path),
        "rows": len(rows),
        "schema_ok": schema_ok,
        "expected_timestamps": len(expected),
        "observed_nonempty_timestamps": len(observed),
        "missing_link_timestamps": len(expected - observed),
        "unexpected_timestamps": len(unexpected),
        "timestamps_nondecreasing_in_file": timestamps_in_file == sorted(timestamps_in_file),
        "duplicate_timestamp_path_pairs": duplicate_pairs,
        "invalid_rows": invalid,
        "nan_count": nan_count,
        "inf_count": inf_count,
        "los_flags": sorted(los_values),
        "delay_min_s": min(delays) if delays else None,
        "delay_max_s": max(delays) if delays else None,
        "gain_min_db": min(gains) if gains else None,
        "gain_max_db": max(gains) if gains else None,
        "doppler_min_hz": min(dopplers) if dopplers else None,
        "doppler_max_hz": max(dopplers) if dopplers else None,
        "max_abs_doppler_hz": max_abs_doppler,
        "theoretical_doppler_hz": THEORETICAL_DOPPLER_HZ,
        "mpc_count_mean": mean(mpc_counts) if mpc_counts else 0.0,
        "mpc_count_p5": percentile([float(value) for value in mpc_counts], 0.05),
        "mpc_count_p50": median(mpc_counts) if mpc_counts else None,
        "mpc_count_p95": percentile([float(value) for value in mpc_counts], 0.95),
    }
    report["pass"] = (
        schema_ok and bool(rows) and not unexpected and invalid == 0 and nan_count == 0 and inf_count == 0
        and duplicate_pairs == 0 and report["timestamps_nondecreasing_in_file"]
        and los_values <= {0, 1} and (not delays or min(delays) >= 0.0)
        and max_abs_doppler <= THEORETICAL_DOPPLER_HZ * 1.001
    )
    output = args.output or (
        ROOT / "analysis" / "station_checkpoints"
        / f"{args.scene}_{args.resolution}m_{args.station.lower()}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    report["report_path"] = str(output)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
