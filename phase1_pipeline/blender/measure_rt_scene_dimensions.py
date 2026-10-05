from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1 :] if "--" in argv else argv[1:]
    parser = argparse.ArgumentParser(description="Measure key object dimensions for RT scene validation.")
    parser.add_argument("--blend", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args(argv)


def bbox(obj: bpy.types.Object) -> list[float]:
    pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    xs, ys, zs = [p.x for p in pts], [p.y for p in pts], [p.z for p in pts]
    return [min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)]


def dims_from_bbox(b: list[float]) -> list[float]:
    return [b[1] - b[0], b[3] - b[2], b[5] - b[4]]


def mesh_stats(obj: bpy.types.Object) -> dict:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(depsgraph)
    mesh = ev.to_mesh()
    try:
        area = 0.0
        for poly in mesh.polygons:
            area += poly.area
        return {
            "vertices": len(mesh.vertices),
            "edges": len(mesh.edges),
            "polygons": len(mesh.polygons),
            "surface_area_local_m2": area,
        }
    finally:
        ev.to_mesh_clear()


def world_xy_points(obj: bpy.types.Object) -> list[Vector]:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(depsgraph)
    mesh = ev.to_mesh()
    try:
        pts = []
        seen = set()
        for v in mesh.vertices:
            p = obj.matrix_world @ v.co
            key = (round(p.x, 1), round(p.y, 1))
            if key not in seen:
                seen.add(key)
                pts.append(Vector((p.x, p.y, 0.0)))
        return pts
    finally:
        ev.to_mesh_clear()


def nearest_neighbor_summary(points: list[Vector]) -> dict:
    if len(points) < 2:
        return {}
    sample = points[: min(len(points), 2000)]
    distances = []
    for i, p in enumerate(sample):
        best = None
        for j, q in enumerate(sample):
            if i == j:
                continue
            d = (p - q).length
            if d > 1e-6 and (best is None or d < best):
                best = d
        if best is not None:
            distances.append(best)
    distances.sort()
    if not distances:
        return {}
    return {
        "nearest_xy_min_m": distances[0],
        "nearest_xy_p50_m": distances[len(distances) // 2],
        "nearest_xy_p95_m": distances[int((len(distances) - 1) * 0.95)],
    }


def object_payload(obj: bpy.types.Object) -> dict:
    b = bbox(obj)
    payload = {
        "name": obj.name,
        "type": obj.type,
        "bbox": b,
        "dimensions_m": dims_from_bbox(b),
        "location": [obj.location.x, obj.location.y, obj.location.z],
        "scale": [obj.scale.x, obj.scale.y, obj.scale.z],
        "sionna_bsdf_id": obj.get("sionna_bsdf_id"),
        "material_names": [m.name for m in obj.data.materials] if getattr(obj, "data", None) and hasattr(obj.data, "materials") else [],
    }
    if obj.type == "MESH":
        payload.update(mesh_stats(obj))
    return payload


def main() -> None:
    args = parse_args()
    bpy.ops.wm.open_mainfile(filepath=str(Path(args.blend).resolve()))
    key_names = ["Railway", "Mountain_Granite"]
    key_prefixes = ("Train", "RT_Tunnel", "GNB_")
    objects = []
    for obj in bpy.context.scene.objects:
        if obj.name in key_names or obj.name.startswith(key_prefixes):
            objects.append(obj)
    result = {"blend": str(Path(args.blend).resolve()), "objects": [object_payload(obj) for obj in objects]}
    railway = bpy.data.objects.get("Railway")
    if railway:
        points = world_xy_points(railway)
        b = bbox(railway)
        result["railway_xy_point_count"] = len(points)
        result["railway_bbox_perimeter_m"] = 2.0 * ((b[1] - b[0]) + (b[3] - b[2]))
        result["railway_nearest_neighbor_xy"] = nearest_neighbor_summary(points)
    Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
