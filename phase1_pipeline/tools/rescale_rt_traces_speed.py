from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rescale Sionna RT trace timestamps and Doppler for a new train speed.")
    parser.add_argument("--pipeline", required=True)
    parser.add_argument("--old-speed-kmh", type=float, required=True)
    parser.add_argument("--new-speed-kmh", type=float, required=True)
    parser.add_argument("--backup-dir-name", default="speed120_backup_20260615")
    return parser.parse_args()


def rescale_csv(csv_path: Path, backup_path: Path, time_scale: float, doppler_scale: float) -> dict:
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    if not backup_path.exists():
        shutil.copy2(csv_path, backup_path)
    tmp_path = csv_path.with_suffix(csv_path.suffix + ".tmp")
    rows = 0
    timestamps = set()
    max_abs_doppler = 0.0
    with backup_path.open("r", encoding="utf-8", newline="") as source, tmp_path.open("w", encoding="utf-8", newline="") as target:
        reader = csv.DictReader(source)
        writer = csv.DictWriter(target, fieldnames=reader.fieldnames)
        writer.writeheader()
        for row in reader:
            row["timestamp_ns"] = str(int(round(int(row["timestamp_ns"]) * time_scale)))
            row["doppler_hz"] = repr(float(row["doppler_hz"]) * doppler_scale)
            timestamps.add(row["timestamp_ns"])
            max_abs_doppler = max(max_abs_doppler, abs(float(row["doppler_hz"])))
            writer.writerow(row)
            rows += 1
    tmp_path.replace(csv_path)
    return {"file": str(csv_path), "rows": rows, "snapshots": len(timestamps), "max_abs_doppler_hz": max_abs_doppler}


def main() -> None:
    args = parse_args()
    pipeline = Path(args.pipeline).resolve()
    backup_root = pipeline / args.backup_dir_name
    time_scale = args.old_speed_kmh / args.new_speed_kmh
    doppler_scale = args.new_speed_kmh / args.old_speed_kmh
    audit = {
        "old_speed_kmh": args.old_speed_kmh,
        "new_speed_kmh": args.new_speed_kmh,
        "time_scale": time_scale,
        "doppler_scale": doppler_scale,
        "outputs": [],
    }
    for output_dir in sorted(pipeline.glob("output_*_full_sionna_final_physics")):
        csv_files = sorted(output_dir.glob("mpc_gnb_*.csv"))
        if not csv_files:
            continue
        output_audit = {"output_dir": str(output_dir), "csv_files": []}
        for csv_path in csv_files:
            backup_path = backup_root / output_dir.name / csv_path.name
            output_audit["csv_files"].append(rescale_csv(csv_path, backup_path, time_scale, doppler_scale))
        audit["outputs"].append(output_audit)
    audit_path = pipeline / "speed350_rescale_audit.json"
    audit_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print(f"Wrote {audit_path}")


if __name__ == "__main__":
    main()
