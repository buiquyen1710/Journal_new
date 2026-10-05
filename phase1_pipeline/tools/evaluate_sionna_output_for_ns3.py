from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Sionna RT scene output for ns-3/adaptive handover readiness.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--scene-id", required=True)
    parser.add_argument("--terrain-type", default="")
    return parser.parse_args()


def db10(value: float) -> float:
    return 10.0 * math.log10(max(value, 1e-300))


def analyze_station(csv_path: Path, sample_count: int) -> dict:
    rows = list(csv.DictReader(csv_path.open("r", encoding="utf-8")))
    by_ts: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        by_ts[int(row["timestamp_ns"])].append(row)
    counts = Counter({ts: len(items) for ts, items in by_ts.items()})
    path_counts = list(counts.values())
    total_power_db = []
    strongest_db = []
    rms_delay_us = []
    max_doppler = []
    los_snapshots = 0
    for ts in sorted(by_ts):
        items = by_ts[ts]
        powers = []
        delays = []
        dops = []
        has_los = False
        for row in items:
            re = float(row["amplitude_real"])
            im = float(row["amplitude_imag"])
            power = re * re + im * im
            powers.append(power)
            delays.append(float(row["delay_s"]))
            dops.append(abs(float(row["doppler_hz"])))
            has_los = has_los or int(float(row["los_flag"])) == 1
        total = sum(powers)
        total_power_db.append(db10(total))
        strongest_db.append(db10(max(powers)))
        if total > 0.0:
            mean_delay = sum(power * delay for power, delay in zip(powers, delays)) / total
            mean_delay2 = sum(power * delay * delay for power, delay in zip(powers, delays)) / total
            rms_delay_us.append(math.sqrt(max(0.0, mean_delay2 - mean_delay * mean_delay)) * 1e6)
        else:
            rms_delay_us.append(0.0)
        max_doppler.append(max(dops) if dops else 0.0)
        if has_los:
            los_snapshots += 1
    return {
        "csv": str(csv_path),
        "rows": len(rows),
        "snapshots": len(by_ts),
        "missing_snapshots": sample_count - len(by_ts),
        "path_count_min": min(path_counts) if path_counts else 0,
        "path_count_median": median(path_counts) if path_counts else 0.0,
        "path_count_max": max(path_counts) if path_counts else 0,
        "los_snapshots": los_snapshots,
        "nlos_only_snapshots": len(by_ts) - los_snapshots,
        "total_power_db_min": min(total_power_db) if total_power_db else None,
        "total_power_db_median": median(total_power_db) if total_power_db else None,
        "total_power_db_max": max(total_power_db) if total_power_db else None,
        "strongest_db_median": median(strongest_db) if strongest_db else None,
        "rms_delay_us_median": median(rms_delay_us) if rms_delay_us else None,
        "rms_delay_us_max": max(rms_delay_us) if rms_delay_us else None,
        "max_doppler_hz": max(max_doppler) if max_doppler else None,
    }


def best_gnb_segments(output_dir: Path, metadata: dict) -> tuple[dict, list[dict], int]:
    station_series = {}
    for csv_path in sorted(output_dir.glob("mpc_gnb_*.csv")):
        station = csv_path.stem.replace("mpc_", "").upper()
        by_ts = defaultdict(float)
        for row in csv.DictReader(csv_path.open("r", encoding="utf-8")):
            re = float(row["amplitude_real"])
            im = float(row["amplitude_imag"])
            by_ts[int(row["timestamp_ns"])] += re * re + im * im
        station_series[station] = by_ts
    if not station_series:
        return {}, [], 0
    covered_times = sorted(set.union(*(set(series.keys()) for series in station_series.values())))
    pts = metadata.get("rx_trajectory_samples", [])
    cum = [0.0]
    for idx in range(1, len(pts)):
        cum.append(cum[-1] + math.dist(pts[idx], pts[idx - 1]))
    best_sequence = []
    for idx, ts in enumerate(covered_times):
        scores = {station: db10(series.get(ts, 0.0)) for station, series in station_series.items() if series.get(ts, 0.0) > 0.0}
        if not scores:
            continue
        best = max(scores, key=scores.get)
        best_sequence.append((idx, best))
    counts = Counter(best for _, best in best_sequence)
    segments = []
    if best_sequence:
        start_idx, current = best_sequence[0]
        prev_idx = start_idx
        for idx, best in best_sequence[1:]:
            if best != current:
                segments.append({"station": current, "start_idx": start_idx, "end_idx": prev_idx, "start_m": cum[start_idx], "end_m": cum[prev_idx]})
                start_idx = idx
                current = best
            prev_idx = idx
        segments.append({"station": current, "start_idx": start_idx, "end_idx": prev_idx, "start_m": cum[start_idx], "end_m": cum[prev_idx]})
    return dict(counts), segments, len(covered_times)


def readiness(stations: list[dict], metadata: dict, manifest: list[dict], network_snapshots: int) -> tuple[str, list[str], list[str]]:
    issues = []
    warnings = []
    if not stations:
        issues.append("No station CSV files were found.")
    if any(item.get("backend") != "sionna" for item in manifest):
        issues.append("At least one station did not report backend=sionna.")
    expected = len(metadata.get("rx_trajectory_samples", []))
    if expected and network_snapshots < expected:
        issues.append(f"Network coverage is missing {expected - network_snapshots} RX snapshots.")
    for station in stations:
        if station["missing_snapshots"] != 0:
            warnings.append(f"{Path(station['csv']).name} is missing {station['missing_snapshots']} snapshots; this is acceptable if another gNB covers those positions.")
        if station["path_count_median"] <= 1:
            issues.append(f"{Path(station['csv']).name} has very low median path count.")
    if not metadata.get("all_gnb_positions_m"):
        issues.append("No gNB positions were found in metadata.")
    status = "READY_FOR_NS3_HANDOVER_BASELINE" if not issues else "NEEDS_REVIEW"
    return status, issues, warnings


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    metadata_path = output_dir / "scene_metadata.json"
    manifest_path = output_dir / "trace_manifest.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    sample_count = len(metadata.get("rx_trajectory_samples", []))
    stations = [analyze_station(path, sample_count) for path in sorted(output_dir.glob("mpc_gnb_*.csv"))]
    best_counts, segments, network_snapshots = best_gnb_segments(output_dir, metadata)
    status, issues, warnings = readiness(stations, metadata, manifest, network_snapshots)
    payload = {
        "scene_id": args.scene_id,
        "terrain_type": args.terrain_type,
        "output_dir": str(output_dir),
        "status": status,
        "issues": issues,
        "warnings": warnings,
        "track_length_m": metadata.get("track_length_m"),
        "rx_samples": sample_count,
        "network_snapshots": network_snapshots,
        "gnb_positions_m": metadata.get("all_gnb_positions_m", []),
        "stations": stations,
        "best_gnb_counts": best_counts,
        "best_gnb_segments": segments,
    }
    (output_dir / "technical_ns3_evaluation.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        f"# {args.scene_id} Technical ns-3 Evaluation",
        "",
        f"- Status: `{status}`",
        f"- Terrain type: `{args.terrain_type}`",
        f"- Track length: `{metadata.get('track_length_m')}` m",
        f"- RX samples: `{sample_count}`",
        f"- Network-covered samples: `{network_snapshots}`",
        f"- gNB count: `{len(metadata.get('all_gnb_positions_m', []))}`",
        "",
        "## Station Statistics",
        "",
        "| Station | Rows | Snapshots | Missing | Path min/median/max | LOS snapshots | NLOS-only | Total power dB min/median/max | RMS delay us median/max | Max Doppler Hz |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for station in stations:
        label = Path(station["csv"]).stem.replace("mpc_", "").upper()
        power = "n/a" if station["total_power_db_min"] is None else f"{station['total_power_db_min']:.1f}/{station['total_power_db_median']:.1f}/{station['total_power_db_max']:.1f}"
        delay = "n/a" if station["rms_delay_us_median"] is None else f"{station['rms_delay_us_median']:.3f}/{station['rms_delay_us_max']:.3f}"
        doppler = "n/a" if station["max_doppler_hz"] is None else f"{station['max_doppler_hz']:.1f}"
        lines.append(
            f"| {label} | {station['rows']} | {station['snapshots']} | {station['missing_snapshots']} | "
            f"{station['path_count_min']}/{station['path_count_median']:.1f}/{station['path_count_max']} | "
            f"{station['los_snapshots']} | {station['nlos_only_snapshots']} | {power} | {delay} | {doppler} |"
        )
    lines.extend(["", "## Adaptive Handover Signal", "", f"- Best-gNB sample counts: `{best_counts}`"])
    for segment in segments:
        lines.append(f"- `{segment['station']}`: samples {segment['start_idx']}-{segment['end_idx']}, approx {segment['start_m']:.1f}-{segment['end_m']:.1f} m")
    if issues:
        lines.extend(["", "## Issues", ""])
        lines.extend(f"- {issue}" for issue in issues)
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    lines.extend([
        "",
        "## Assessment",
        "",
        "This output is suitable for ns-3/adaptive handover if all stations report backend=sionna, all RX snapshots are present, and adjacent gNB dominance changes along the track. The CSV files provide per-path delay, complex amplitude, angle and Doppler information for network-level trace conversion.",
    ])
    (output_dir / "technical_ns3_evaluation.md").write_text("\n".join(lines), encoding="utf-8")
    print(status)


if __name__ == "__main__":
    main()
