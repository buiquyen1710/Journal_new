from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

import addon_utils
import bpy


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--osm", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--mode", default="3Dsimple", choices=["3Dsimple", "2D"])
    parser.add_argument("--single-object", action="store_true")
    return parser.parse_args(argv)


def classify_mesh(obj: bpy.types.Object) -> str:
    name = obj.name.lower()
    if "rail" in name or "duong" in name:
        return "rail"
    if "road" in name or "path" in name or "street" in name or "highway" in name:
        return "road"
    if "water" in name or "river" in name or "lake" in name:
        return "water"
    if obj.dimensions.z > 2.0:
        return "building"
    return "other"


def main() -> None:
    args = parse_args()
    addon_utils.enable("blosm", default_set=True, persistent=False)
    sys.modules["gui"] = importlib.import_module("blosm.gui")

    prefs = bpy.context.preferences.addons["blosm"].preferences
    data_dir = Path(args.out).resolve().parent / "blosm_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    prefs.dataDir = str(data_dir)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()

    props = bpy.context.scene.blosm
    props.dataType = "osm"
    props.osmSource = "file"
    props.osmFilepath = str(Path(args.osm).resolve())
    props.mode = args.mode
    props.buildings = True
    props.highways = True
    props.railways = True
    props.water = True
    props.forests = True
    props.vegetation = True
    props.singleObject = bool(args.single_object)
    props.importForExport = True
    props.levelHeight = 3.2
    props.loadMissingMembers = False
    props.relativeToInitialImport = False

    result = bpy.ops.blosm.import_data()
    print("blosm.import_data result:", result)

    rows = []
    counts = {"building": 0, "rail": 0, "road": 0, "water": 0, "other": 0}
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        kind = classify_mesh(obj)
        counts[kind] += 1
        rows.append(
            {
                "name": obj.name,
                "kind": kind,
                "dimensions_m": [
                    round(float(obj.dimensions.x), 3),
                    round(float(obj.dimensions.y), 3),
                    round(float(obj.dimensions.z), 3),
                ],
            }
        )

    building_heights = [row["dimensions_m"][2] for row in rows if row["kind"] == "building"]
    report = {
        "osm": str(Path(args.osm).resolve()),
        "out": str(Path(args.out).resolve()),
        "blosm_mode": props.mode,
        "object_count": len(bpy.context.scene.objects),
        "mesh_count": len(rows),
        "counts": counts,
        "building_height_min_m": min(building_heights) if building_heights else None,
        "building_height_max_m": max(building_heights) if building_heights else None,
        "building_height_unique_m": sorted(set(building_heights))[:60],
        "tallest_meshes": sorted(rows, key=lambda item: item["dimensions_m"][2], reverse=True)[:30],
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out))
    Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
