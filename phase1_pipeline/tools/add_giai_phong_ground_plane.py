from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = argv[1:]
    parser = argparse.ArgumentParser(description="Add a continuous RT ground plane to the Giai Phong scene.")
    parser.add_argument("--output-blend", required=True)
    parser.add_argument("--margin-x-m", type=float, default=220.0)
    parser.add_argument("--margin-y-m", type=float, default=180.0)
    return parser.parse_args(argv)


def make_material() -> bpy.types.Material:
    material = bpy.data.materials.get("RT_Ground_Concrete_Rough") or bpy.data.materials.new("RT_Ground_Concrete_Rough")
    material.diffuse_color = (0.36, 0.36, 0.34, 1.0)
    material["sionna_bsdf_id"] = "mat-vn_concrete_rough"
    material["mitsuba_bsdf_id"] = "mat-vn_concrete_rough"
    return material


def object_bbox_xy(obj: bpy.types.Object) -> tuple[float, float, float, float]:
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    xs = [corner.x for corner in corners]
    ys = [corner.y for corner in corners]
    return min(xs), max(xs), min(ys), max(ys)


def main() -> None:
    args = parse_args()
    trajectory = bpy.data.objects.get("RT_Trajectory_Centerline")
    if trajectory is None:
        raise KeyError("RT_Trajectory_Centerline not found.")
    min_x, max_x, min_y, max_y = object_bbox_xy(trajectory)
    min_x -= args.margin_x_m
    max_x += args.margin_x_m
    min_y -= args.margin_y_m
    max_y += args.margin_y_m
    z = -0.08

    old = bpy.data.objects.get("RT_Ground_Plane_Corridor")
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)

    mesh = bpy.data.meshes.new("RT_Ground_Plane_Corridor_Mesh")
    vertices = [
        (min_x, min_y, z),
        (max_x, min_y, z),
        (max_x, max_y, z),
        (min_x, max_y, z),
    ]
    mesh.from_pydata(vertices, [], [(0, 1, 2, 3)])
    mesh.update()
    obj = bpy.data.objects.new("RT_Ground_Plane_Corridor", mesh)
    bpy.context.collection.objects.link(obj)
    material = make_material()
    obj.data.materials.append(material)
    obj["sionna_bsdf_id"] = "mat-vn_concrete_rough"
    obj["mitsuba_bsdf_id"] = "mat-vn_concrete_rough"
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.output_blend)))
    print(f"Saved ground-enhanced scene to {args.output_blend}")
    print(f"Ground extents x=[{min_x:.2f}, {max_x:.2f}], y=[{min_y:.2f}, {max_y:.2f}], z={z:.2f}")


if __name__ == "__main__":
    main()
