#!/usr/bin/env python3
"""Audit dense MPC-to-trace index preservation and emit the required CSV."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import statistics
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CONVERTER_PATH = ROOT / "scratch/group_b_handover_eval/tools/convert_mpc_to_siolena_group_b.py"
SPEC = importlib.util.spec_from_file_location("group_b_converter", CONVERTER_PATH)
assert SPEC and SPEC.loader
CONVERTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONVERTER)


def parse_blocks(path: Path) -> list[dict[str, object]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    blocks: list[dict[str, object]] = []
    cursor = 0
    names = ["delay", "gain", "phase", "el_aod", "az_aod", "el_aoa", "az_aoa", "doppler"]
    while cursor < len(lines):
        count = int(lines[cursor])
        cursor += 1
        values: dict[str, object] = {"count": count}
        if count:
            for name in names:
                row = [float(value) for value in lines[cursor].split(",")]
                if len(row) != count:
                    raise AssertionError(f"{path}: {name} has {len(row)} values, expected {count}")
                values[name] = row
                cursor += 1
        blocks.append(values)
    return blocks


def expected_block(paths: list[dict[str, float]]) -> dict[str, object]:
    if not paths:
        return {"count": 0}
    return {
        "count": len(paths),
        "delay": [path["delay"] for path in paths],
        "gain": [path["gain"] for path in paths],
        "phase": [path["phase"] for path in paths],
        "el_aod": [path["el_aod"] for path in paths],
        "az_aod": [path["az_aod"] for path in paths],
        "el_aoa": [path["el_aoa"] for path in paths],
        "az_aoa": [path["az_aoa"] for path in paths],
        "doppler": [path["doppler"] for path in paths],
    }


def blocks_equal(actual: dict[str, object], expected: dict[str, object]) -> bool:
    if actual["count"] != expected["count"]:
        return False
    for key in expected.keys() - {"count"}:
        left = actual[key]
        right = expected[key]
        if not isinstance(left, list) or not isinstance(right, list) or len(left) != len(right):
            return False
        if any(not math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-15) for a, b in zip(left, right)):
            return False
    return True


def percentile(values: list[float], percent: float) -> float:
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percent / 100.0
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - rank) + ordered[upper] * (rank - lower)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--shadow", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--reader-roundtrip-ok", action="store_true")
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    metadata = json.loads(Path(config["metadata_path"]).read_text(encoding="utf-8"))
    trajectory = metadata["rx_trajectory_samples"]
    planned = CONVERTER.build_planned_timestamps_ns(trajectory, config["train_speed_kmh"])
    source = [
        CONVERTER.read_snapshots(Path(config["mpc_path"]) / filename)
        for filename in config["mpc_csv_files"]
    ]
    channel_dir = args.shadow / "Output/Ns3/Channel"
    channels = sorted(channel_dir.glob("Tx*Rx*.txt"))
    if len(channels) != len(source):
        raise AssertionError(f"channel files={len(channels)}, expected={len(source)}")
    converted = [parse_blocks(path) for path in channels]
    if any(len(blocks) != len(planned) for blocks in converted):
        raise AssertionError("not every converted channel contains the full planned timeline")

    letters = [chr(ord("A") + index) for index in range(len(source))]
    fieldnames = ["snapshot_index", "source_timestamp_s"]
    for letter in letters:
        fieldnames.extend([f"source_paths_{letter}", f"converted_paths_{letter}"])
    fieldnames.extend(
        [
            "all_gnb_zero_source",
            "all_gnb_zero_converted",
            "block_preserved",
            "synthetic_path_present",
            "reader_roundtrip_ok",
            "notes",
        ]
    )

    rows: list[dict[str, object]] = []
    zero_source_total = 0
    zero_converted_total = 0
    synthetic_total = 0
    exact_total = 0
    for index, timestamp in enumerate(planned):
        source_paths = [snapshots.get(timestamp, []) for snapshots in source]
        actual = [blocks[index] for blocks in converted]
        expected = [expected_block(paths) for paths in source_paths]
        exact = all(blocks_equal(a, e) for a, e in zip(actual, expected))
        source_counts = [len(paths) for paths in source_paths]
        converted_counts = [int(block["count"]) for block in actual]
        all_zero_source = all(count == 0 for count in source_counts)
        all_zero_converted = all(count == 0 for count in converted_counts)
        synthetic = any(
            (source_count == 0 and converted_count != 0)
            or any(gain == 1e-18 for gain in block.get("gain", []))
            for source_count, converted_count, block in zip(source_counts, converted_counts, actual)
        )
        zero_source_total += sum(count == 0 for count in source_counts)
        zero_converted_total += sum(count == 0 for count in converted_counts)
        synthetic_total += int(synthetic)
        exact_total += int(exact)
        row: dict[str, object] = {
            "snapshot_index": index,
            "source_timestamp_s": f"{timestamp / 1e9:.9f}",
            "all_gnb_zero_source": "YES" if all_zero_source else "NO",
            "all_gnb_zero_converted": "YES" if all_zero_converted else "NO",
            "block_preserved": "YES" if exact else "NO",
            "synthetic_path_present": "YES" if synthetic else "NO",
            "reader_roundtrip_ok": "YES" if args.reader_roundtrip_ok else "NOT_RUN",
            "notes": "all-gNB zero-path state" if all_zero_source else ("per-link zero present" if 0 in source_counts else "physical MPC state"),
        }
        for letter, source_count, converted_count in zip(letters, source_counts, converted_counts):
            row[f"source_paths_{letter}"] = source_count
            row[f"converted_paths_{letter}"] = converted_count
        rows.append(row)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    duration = float(metadata["track_length_m"]) / (float(config["train_speed_kmh"]) / 3.6)
    replay_interval = duration / (len(planned) - 1)
    errors_ms = [(index * replay_interval - timestamp / 1e9) * 1000 for index, timestamp in enumerate(planned)]
    absolute_ms = [abs(value) for value in errors_ms]
    summary = {
        "source_samples": len(planned),
        "converted_states_per_file": [len(blocks) for blocks in converted],
        "channel_files": len(channels),
        "ue_positions": len(trajectory),
        "first_time_s": planned[0] / 1e9,
        "last_source_time_s": planned[-1] / 1e9,
        "replay_interval_ms": replay_interval * 1000,
        "missing_per_link_source": zero_source_total,
        "zero_path_blocks_converted": zero_converted_total,
        "all_gnb_zero_indices": [i for i, row in enumerate(rows) if row["all_gnb_zero_source"] == "YES"],
        "synthetic_snapshot_count": synthetic_total,
        "exactly_preserved_snapshots": exact_total,
        "timing_mean_signed_ms": statistics.fmean(errors_ms),
        "timing_mae_ms": statistics.fmean(absolute_ms),
        "timing_median_absolute_ms": statistics.median(absolute_ms),
        "timing_rms_ms": math.sqrt(statistics.fmean(value * value for value in errors_ms)),
        "timing_p95_absolute_ms": percentile(absolute_ms, 95),
        "timing_max_absolute_ms": max(absolute_ms),
        "timing_max_index": absolute_ms.index(max(absolute_ms)),
        "timing_count_gt_1ms": sum(value > 1 for value in absolute_ms),
        "timing_count_gt_5ms": sum(value > 5 for value in absolute_ms),
        "timing_count_gt_10ms": sum(value > 10 for value in absolute_ms),
        "timing_count_gt_20ms": sum(value > 20 for value in absolute_ms),
    }
    print(json.dumps(summary, indent=2))
    if zero_source_total != 323 or zero_converted_total != 323:
        raise AssertionError("expected exactly 323 per-link zero states")
    if summary["all_gnb_zero_indices"] != [478, 479, 573, 574, 627, 628, 664, 683, 684]:
        raise AssertionError("all-gNB-zero indices do not match the diagnosed set")
    if synthetic_total or exact_total != len(planned):
        raise AssertionError("shadow blocks do not exactly represent the source timeline")


if __name__ == "__main__":
    main()
