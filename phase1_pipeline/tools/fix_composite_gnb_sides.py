from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend", required=True)
    parser.add_argument("--report", required=True)
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    blend = Path(args.blend)
    report_path = Path(args.report)
    report = json.loads(report_path.read_text(encoding="utf-8"))

    bpy.ops.wm.open_mainfile(filepath=str(blend))

    module_offsets = {}
    for module in report["modules"]:
        if "GiaiPhong" in module["id"]:
            offset = 65.0
        elif "LongBien" in module["id"]:
            offset = 80.0
        elif "HaiDuong" in module["id"]:
            offset = 80.0
        elif "HaiPhong" in module["id"]:
            offset = 75.0
        elif "LangCo" in module["id"]:
            offset = 100.0
        else:
            offset = 90.0
        module_offsets[module["id"]] = offset

    module_seen = {module["id"]: 0 for module in report["modules"]}
    for station in report["base_stations"]:
        module_id = next(module_id for module_id in module_offsets if module_id in station["name"])
        idx = module_seen[module_id]
        module_seen[module_id] += 1
        y = module_offsets[module_id] * (1.0 if idx % 2 else -1.0)
        station["position_m"][1] = round(y, 3)
        for suffix in ("mast", "antenna"):
            obj = bpy.data.objects.get(f"{station['name']}_{suffix}")
            if obj is not None:
                obj.location.y = y

    report["gnb_placement_note"] = "gNBs alternate sides of the visible track inside each module; offsets are 65-100 m depending on urban/open/mountain environment."
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    print(json.dumps({"updated_gnbs": len(report["base_stations"]), "module_counts": module_seen}, indent=2))


if __name__ == "__main__":
    main()
