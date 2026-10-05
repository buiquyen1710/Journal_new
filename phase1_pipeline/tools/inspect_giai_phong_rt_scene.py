from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def bbox_center(obj):
    if not obj.bound_box:
        return [obj.location.x, obj.location.y, obj.location.z]
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    return [
        sum(c.x for c in corners) / len(corners),
        sum(c.y for c in corners) / len(corners),
        sum(c.z for c in corners) / len(corners),
    ]


def dims(obj):
    return [obj.dimensions.x, obj.dimensions.y, obj.dimensions.z]


def main() -> None:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    out_path = Path(argv[0]) if argv else Path(bpy.data.filepath).with_suffix(".inspect.json")
    names = [
        "RT_Trajectory_Centerline",
        "RT_Rail_Left_meter_gauge",
        "RT_Rail_Right_meter_gauge",
        "RT_Ballast_Trackbed_4m",
        "Train_Static_RT_Body",
        "GNB_A_Mast",
        "GNB_A_Antenna",
        "GNB_B_Mast",
        "GNB_B_Antenna",
        "GNB_C_Mast",
        "GNB_C_Antenna",
        "GNB_D_Mast",
        "GNB_D_Antenna",
    ]
    objects = {}
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None:
            objects[name] = None
            continue
        objects[name] = {
            "type": obj.type,
            "location": [obj.location.x, obj.location.y, obj.location.z],
            "bbox_center": bbox_center(obj),
            "dimensions": dims(obj),
            "rotation_euler": [obj.rotation_euler.x, obj.rotation_euler.y, obj.rotation_euler.z],
            "sionna_bsdf_id": obj.get("sionna_bsdf_id"),
            "active_material": obj.active_material.name if obj.active_material else None,
        }
    rail_like = [
        obj.name
        for obj in bpy.data.objects
        if obj.type == "CURVE" and ("RT_Rail" in obj.name or "Trajectory" in obj.name or "sắt" in obj.name.lower())
    ]
    payload = {
        "blend_file": bpy.data.filepath,
        "object_count": len(bpy.data.objects),
        "mesh_count": sum(1 for obj in bpy.data.objects if obj.type == "MESH"),
        "curve_count": sum(1 for obj in bpy.data.objects if obj.type == "CURVE"),
        "rail_like_curves": rail_like,
        "objects": objects,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
