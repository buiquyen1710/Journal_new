from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

from run_experiment import SCENES as SELECTED_SCENES


ROOT = Path(__file__).resolve().parent
SPEED_MPS = 350.0 / 3.6
THEORETICAL_DOPPLER_HZ = 30e9 * SPEED_MPS / 299_792_458.0


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def trajectory_timestamps(metadata: dict) -> list[int]:
    points = metadata["rx_trajectory_samples"]
    distance = 0.0
    result = [0]
    for previous, current in zip(points, points[1:]):
        distance += math.dist(previous[:3], current[:3])
        result.append(int(round(distance / SPEED_MPS * 1e9)))
    return result


def analyze_case(scene: str, spacing: int) -> tuple[list[dict], list[str]]:
    case = ROOT / "sionna" / scene / f"{spacing}m"
    metadata_path = case / "scene_metadata.json"
    if spacing != 25 and not (case / "trace_manifest.json").exists():
        return [], [f"{scene} {spacing}m: case is incomplete (no trace_manifest.json); partial CSVs were not validated"]
    if spacing == 25 and not list(case.glob("mpc_gnb_*.csv")):
        source = ROOT.parents[1] / SELECTED_SCENES[scene]["baseline"]
    else:
        source = case
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    expected = set(trajectory_timestamps(metadata))
    station_sets: list[set[int]] = []
    rows_out: list[dict] = []
    notes: list[str] = []
    all_invalid = all_nan = all_inf = 0
    for csv_path in sorted(source.glob("mpc_gnb_*.csv")):
        by_time: dict[int, list[dict]] = defaultdict(list)
        invalid = nan_count = inf_count = 0
        delays: list[float] = []
        dopplers: list[float] = []
        gains_db: list[float] = []
        los_times: set[int] = set()
        with csv_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                try:
                    numeric = [float(row[key]) for key in ("delay_s", "amplitude_real", "amplitude_imag", "doppler_hz")]
                except (KeyError, TypeError, ValueError):
                    invalid += 1
                    continue
                nan_count += sum(math.isnan(value) for value in numeric)
                inf_count += sum(math.isinf(value) for value in numeric)
                if any(not math.isfinite(value) for value in numeric):
                    invalid += 1
                    continue
                ts = int(row["timestamp_ns"])
                by_time[ts].append(row)
                delays.append(numeric[0])
                dopplers.append(numeric[3])
                magnitude = math.hypot(numeric[1], numeric[2])
                gains_db.append(20.0 * math.log10(max(magnitude, 1e-300)))
                if int(float(row["los_flag"])) == 1:
                    los_times.add(ts)
        times = set(by_time)
        station_sets.append(times)
        counts = [len(by_time[ts]) for ts in sorted(times)]
        all_invalid += invalid
        all_nan += nan_count
        all_inf += inf_count
        rows_out.append({
            "scene": scene,
            "resolution_m": spacing,
            "station": csv_path.stem,
            "num_total_snapshots": len(expected),
            "num_valid_snapshots": len(times),
            "num_missing_links": len(expected - times),
            "num_empty_MPC_snapshots": len(expected - times),
            "num_invalid_values": invalid,
            "nan_count": nan_count,
            "inf_count": inf_count,
            "mean_mpc_count": mean(counts) if counts else 0.0,
            "p5_mpc_count": percentile([float(v) for v in counts], 0.05),
            "p50_mpc_count": median(counts) if counts else None,
            "p95_mpc_count": percentile([float(v) for v in counts], 0.95),
            "los_ratio": len(los_times) / len(times) if times else 0.0,
            "delay_min_s": min(delays) if delays else None,
            "delay_max_s": max(delays) if delays else None,
            "doppler_min_hz": min(dopplers) if dopplers else None,
            "doppler_max_hz": max(dopplers) if dopplers else None,
            "gain_min_db": min(gains_db) if gains_db else None,
            "gain_max_db": max(gains_db) if gains_db else None,
        })
    if not station_sets:
        notes.append(f"{scene} {spacing}m: no MPC CSV files available")
        return rows_out, notes
    union = set().union(*station_sets)
    intersection = set.intersection(*station_sets)
    notes.append(f"{scene} {spacing}m: expected={len(expected)}, network_union={len(union)}, all_gNB_common={len(intersection)}, missing_network={len(expected-union)}")
    observed_max = max((abs(row["doppler_min_hz"] or 0.0) for row in rows_out), default=0.0)
    observed_max = max(observed_max, max((abs(row["doppler_max_hz"] or 0.0) for row in rows_out), default=0.0))
    notes.append(f"{scene} {spacing}m: max_abs_doppler={observed_max:.3f} Hz; theoretical={THEORETICAL_DOPPLER_HZ:.3f} Hz")
    notes.append(f"{scene} {spacing}m: invalid={all_invalid}, NaN={all_nan}, Inf={all_inf}")
    return rows_out, notes


def main() -> None:
    all_rows: list[dict] = []
    notes = ["# RT trace validation", ""]
    for scene in SELECTED_SCENES:
        for spacing in (25, 5, 2):
            if not (ROOT / "sionna" / scene / f"{spacing}m" / "scene_metadata.json").exists():
                continue
            rows, case_notes = analyze_case(scene, spacing)
            all_rows.extend(rows)
            notes.extend(f"- {line}" for line in case_notes)
    output = ROOT / "analysis" / "rt_trace_validation.csv"
    if all_rows:
        with output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(all_rows[0]))
            writer.writeheader()
            writer.writerows(all_rows)
    (ROOT / "analysis" / "rt_trace_validation.md").write_text("\n".join(notes) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
