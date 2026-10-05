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
    parser = argparse.ArgumentParser(description="Validate tunnel alignment against Railway vertices inside Mountain_Granite.")
    parser.add_argument("--blend", required=True)
    parser.add_argument("--report-json", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args(argv)


def bbox(obj: bpy.types.Object) -> tuple[float, float, float, float, float, float]:
    pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    xs, ys, zs = [p.x for p in pts], [p.y for p in pts], [p.z for p in pts]
    return min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)


def points_in_mountain(rail: bpy.types.Object, mountain: bpy.types.Object) -> list[Vector]:
    min_x, max_x, min_y, max_y, _, _ = bbox(mountain)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    ev = rail.evaluated_get(depsgraph)
    mesh = ev.to_mesh()
    try:
        pts = []
        seen = set()
        for vertex in mesh.vertices:
            p = rail.matrix_world @ vertex.co
            if min_x - 8.0 <= p.x <= max_x + 8.0 and min_y - 8.0 <= p.y <= max_y + 8.0:
                key = (round(p.x, 1), round(p.y, 1), round(p.z, 1))
                if key not in seen:
                    seen.add(key)
                    pts.append(Vector((p.x, p.y, p.z)))
        return pts
    finally:
        ev.to_mesh_clear()


def point_segment_distance_xy(p: Vector, a: Vector, b: Vector) -> float:
    ax, ay, bx, by = a.x, a.y, b.x, b.y
    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy
    if denom <= 1e-9:
        return math.hypot(p.x - ax, p.y - ay)
    t = max(0.0, min(1.0, ((p.x - ax) * dx + (p.y - ay) * dy) / denom))
    qx, qy = ax + t * dx, ay + t * dy
    return math.hypot(p.x - qx, p.y - qy)


def distance_to_polyline_xy(p: Vector, centerline: list[Vector]) -> float:
    return min(point_segment_distance_xy(p, a, b) for a, b in zip(centerline, centerline[1:]))


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return ordered[idx]


def main() -> None:
    args = parse_args()
    bpy.ops.wm.open_mainfile(filepath=str(Path(args.blend).resolve()))
    rail = bpy.data.objects.get("Railway")
    mountain = bpy.data.objects.get("Mountain_Granite")
    if rail is None or mountain is None:
        raise RuntimeError("Required objects Railway and Mountain_Granite were not found.")

    report = json.loads(Path(args.report_json).read_text(encoding="utf-8"))
    centerline = [Vector((float(x), float(y), float(z))) for x, y, z in report["centerline"]]
    width = float(report["width_m"])
    height = float(report["height_m"])
    rail_points = points_in_mountain(rail, mountain)
    distances = [distance_to_polyline_xy(p, centerline) for p in rail_points]

    tunnel_objects = [obj for obj in bpy.data.objects if obj.name.startswith("RT_Tunnel_")]
    tunnel_bbox = None
    if tunnel_objects:
        boxes = [bbox(obj) for obj in tunnel_objects]
        tunnel_bbox = [
            min(b[0] for b in boxes),
            max(b[1] for b in boxes),
            min(b[2] for b in boxes),
            max(b[3] for b in boxes),
            min(b[4] for b in boxes),
            max(b[5] for b in boxes),
        ]

    result = {
        "blend": str(Path(args.blend).resolve()),
        "rail_points_checked": len(rail_points),
        "centerline_samples": len(centerline),
        "width_m": width,
        "height_m": height,
        "half_width_m": width / 2.0,
        "mean_rail_to_centerline_xy_m": sum(distances) / len(distances) if distances else None,
        "p95_rail_to_centerline_xy_m": percentile(distances, 0.95),
        "max_rail_to_centerline_xy_m": max(distances) if distances else None,
        "rail_points_outside_half_width": sum(d > width / 2.0 for d in distances),
        "rail_points_outside_80pct_half_width": sum(d > width * 0.4 for d in distances),
        "tunnel_object_count": len(tunnel_objects),
        "tunnel_bbox": tunnel_bbox,
    }
    Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
