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
    parser = argparse.ArgumentParser(description="Measure Railway mesh lateral width around metadata trajectory.")
    parser.add_argument("--blend", required=True)
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args(argv)


def point_segment_distance_xy(p: Vector, a: Vector, b: Vector) -> float:
    dx, dy = b.x - a.x, b.y - a.y
    denom = dx * dx + dy * dy
    if denom <= 1e-9:
        return math.hypot(p.x - a.x, p.y - a.y)
    t = max(0.0, min(1.0, ((p.x - a.x) * dx + (p.y - a.y) * dy) / denom))
    return math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy))


def dist_to_polyline(p: Vector, polyline: list[Vector]) -> float:
    return min(point_segment_distance_xy(p, a, b) for a, b in zip(polyline, polyline[1:]))


def percentile(values: list[float], q: float) -> float:
    values = sorted(values)
    return values[int((len(values) - 1) * q)]


def main() -> None:
    args = parse_args()
    bpy.ops.wm.open_mainfile(filepath=str(Path(args.blend).resolve()))
    metadata = json.loads(Path(args.metadata).read_text(encoding="utf-8"))
    trajectory = [Vector((float(x), float(y), 0.0)) for x, y, _ in metadata["rx_trajectory_samples"]]
    rail = bpy.data.objects.get("Railway")
    train = bpy.data.objects.get("Train")
    if rail is None:
        raise RuntimeError("Railway object not found")
    depsgraph = bpy.context.evaluated_depsgraph_get()
    ev = rail.evaluated_get(depsgraph)
    mesh = ev.to_mesh()
    try:
        distances = []
        seen = set()
        for vertex in mesh.vertices:
            p = rail.matrix_world @ vertex.co
            key = (round(p.x, 1), round(p.y, 1))
            if key in seen:
                continue
            seen.add(key)
            distances.append(dist_to_polyline(Vector((p.x, p.y, 0.0)), trajectory))
    finally:
        ev.to_mesh_clear()

    seg_lengths = [(b - a).length for a, b in zip(trajectory, trajectory[1:])]
    result = {
        "rail_points_checked": len(distances),
        "trajectory_length_m": sum(seg_lengths),
        "trajectory_samples": len(trajectory),
        "rail_lateral_distance_to_trajectory_m": {
            "p50": percentile(distances, 0.50),
            "p75": percentile(distances, 0.75),
            "p90": percentile(distances, 0.90),
            "p95": percentile(distances, 0.95),
            "p99": percentile(distances, 0.99),
            "max": max(distances),
        },
    }
    if train:
        pts = [train.matrix_world @ Vector(c) for c in train.bound_box]
        xs, ys, zs = [p.x for p in pts], [p.y for p in pts], [p.z for p in pts]
        result["train_dimensions_m"] = [max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)]
    Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
