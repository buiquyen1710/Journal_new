from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


TRACK_KEYWORDS = ("rail", "track", "duong_ray", "duongray", "ray", "sleeper", "nurbspath", "railway")


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1 :] if "--" in argv else argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend", required=True)
    parser.add_argument("--out-dir", required=True)
    return parser.parse_args(argv)


def world_bbox(obj: bpy.types.Object) -> list[Vector]:
    return [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]


def bbox_dims(obj: bpy.types.Object) -> tuple[float, float, float]:
    corners = world_bbox(obj)
    xs = [p.x for p in corners]
    ys = [p.y for p in corners]
    zs = [p.z for p in corners]
    return (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))


def surface_area(obj: bpy.types.Object) -> float:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        area = 0.0
        for poly in mesh.polygons:
            area += poly.area
        return area * abs(obj.matrix_world.to_scale().x * obj.matrix_world.to_scale().y)
    finally:
        evaluated.to_mesh_clear()


def is_track(obj: bpy.types.Object) -> bool:
    text = " ".join(
        part.lower()
        for part in (
            obj.name,
            obj.data.name if getattr(obj, "data", None) else "",
            obj.active_material.name if obj.active_material else "",
        )
    )
    return any(keyword in text for keyword in TRACK_KEYWORDS)


def bounds(objects: list[bpy.types.Object]) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for obj in objects:
        for point in world_bbox(obj):
            xs.append(point.x)
            ys.append(point.y)
    return (min(xs), max(xs), min(ys), max(ys))


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(Path(args.blend).resolve()))
    mesh_objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    track_objects = [obj for obj in mesh_objects if is_track(obj)]
    track_bounds = bounds(track_objects or mesh_objects)
    min_x, max_x, min_y, max_y = track_bounds
    loop_estimate = 2.0 * ((max_x - min_x) + (max_y - min_y))
    rows = []
    for obj in sorted(mesh_objects, key=lambda item: item.name.lower()):
        dx, dy, dz = bbox_dims(obj)
        rows.append(
            {
                "name": obj.name,
                "material": obj.active_material.name if obj.active_material else "",
                "is_track": is_track(obj),
                "bbox_x": dx,
                "bbox_y": dy,
                "bbox_z": dz,
                "surface_area": surface_area(obj),
                "scale_x": obj.scale.x,
                "scale_y": obj.scale.y,
                "scale_z": obj.scale.z,
            }
        )
    csv_path = out_dir / "blend_object_inspection.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else ["name"])
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "mesh_object_count": len(mesh_objects),
        "track_object_count": len(track_objects),
        "track_bounds": list(track_bounds),
        "loop_length_estimate": loop_estimate,
        "largest_objects": sorted(rows, key=lambda row: row["surface_area"], reverse=True)[:20],
    }
    (out_dir / "blend_scene_inspection.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
