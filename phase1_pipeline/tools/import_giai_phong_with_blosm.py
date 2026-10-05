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
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    addon_utils.enable("blosm", default_set=True, persistent=False)
    sys.modules["gui"] = importlib.import_module("blosm.gui")
    prefs = bpy.context.preferences.addons["blosm"].preferences
    data_dir = Path(args.out).resolve().parent / "blosm_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    prefs.dataDir = str(data_dir)
    prefs.assetsDir = str(Path(__file__).resolve().parents[3] / "AppDataDummy")

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()

    props = bpy.context.scene.blosm
    props.dataType = "osm"
    props.osmSource = "file"
    props.osmFilepath = str(Path(args.osm).resolve())
    props.mode = "3Dsimple"
    props.buildings = True
    props.highways = True
    props.railways = True
    props.water = True
    props.forests = False
    props.vegetation = False
    props.singleObject = False
    props.importForExport = True
    props.levelHeight = 3.2
    props.loadMissingMembers = False
    props.relativeToInitialImport = False

    result = bpy.ops.blosm.import_data()
    print("blosm.import_data result:", result)

    building_like = []
    rail_like = []
    road_like = []
    water_like = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        name = obj.name.lower()
        dims = obj.dimensions
        item = {
            "name": obj.name,
            "dimensions_m": [round(float(dims.x), 3), round(float(dims.y), 3), round(float(dims.z), 3)],
            "location_m": [
                round(float(obj.location.x), 3),
                round(float(obj.location.y), 3),
                round(float(obj.location.z), 3),
            ],
        }
        if "building" in name:
            building_like.append(item)
        elif "rail" in name:
            rail_like.append(item)
        elif "road" in name or "path" in name or "highway" in name:
            road_like.append(item)
        elif "water" in name:
            water_like.append(item)

    heights = [item["dimensions_m"][2] for item in building_like]
    report = {
        "osm": str(Path(args.osm).resolve()),
        "out": str(Path(args.out).resolve()),
        "blosm_mode": props.mode,
        "object_count": len(bpy.context.scene.objects),
        "mesh_count": sum(1 for obj in bpy.context.scene.objects if obj.type == "MESH"),
        "building_count": len(building_like),
        "rail_object_count": len(rail_like),
        "road_object_count": len(road_like),
        "water_object_count": len(water_like),
        "building_height_min_m": min(heights) if heights else None,
        "building_height_max_m": max(heights) if heights else None,
        "building_height_unique_m": sorted(set(heights))[:40],
        "tallest_buildings": sorted(building_like, key=lambda item: item["dimensions_m"][2], reverse=True)[:20],
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out))
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
