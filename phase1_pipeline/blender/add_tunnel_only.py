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
    parser = argparse.ArgumentParser(description="Add only a physical tunnel through the existing mountain.")
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--tunnel-width-m", type=float, default=11.0)
    parser.add_argument("--tunnel-height-m", type=float, default=8.0)
    parser.add_argument("--segment-m", type=float, default=25.0)
    return parser.parse_args(argv)


def material(name: str, color, bsdf_id: str) -> bpy.types.Material:
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    node = mat.node_tree.nodes.get("Principled BSDF")
    if node:
        node.inputs["Base Color"].default_value = color
        node.inputs["Roughness"].default_value = 0.55
    mat["sionna_bsdf_id"] = bsdf_id
    return mat


def assign(obj: bpy.types.Object, mat: bpy.types.Material, bsdf_id: str) -> None:
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    obj["sionna_bsdf_id"] = bsdf_id


def clean_collection(name: str) -> bpy.types.Collection:
    old = bpy.data.collections.get(name)
    if old:
        for obj in list(old.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        return old
    col = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(col)
    return col


def link_to(obj: bpy.types.Object, col: bpy.types.Collection) -> None:
    for existing in list(obj.users_collection):
        existing.objects.unlink(obj)
    col.objects.link(obj)


def bbox(obj: bpy.types.Object) -> tuple[float, float, float, float, float, float]:
    pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    xs, ys, zs = [p.x for p in pts], [p.y for p in pts], [p.z for p in pts]
    return min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)


class LoopPath:
    def __init__(self, rail: bpy.types.Object):
        min_x, max_x, min_y, max_y, min_z, max_z = bbox(rail)
        z = max(1.2, (min_z + max_z) / 2.0 + 0.5)
        self.points = [
            Vector((min_x, min_y, z)),
            Vector((max_x, min_y, z)),
            Vector((max_x, max_y, z)),
            Vector((min_x, max_y, z)),
            Vector((min_x, min_y, z)),
        ]
        self.lengths = [(b - a).length for a, b in zip(self.points, self.points[1:])]
        self.total = sum(self.lengths)

    def sample(self, s: float) -> tuple[Vector, Vector, Vector]:
        s = max(0.0, min(float(s), self.total))
        elapsed = 0.0
        for a, b, length in zip(self.points, self.points[1:], self.lengths):
            if s <= elapsed + length:
                ratio = 0.0 if length <= 1e-9 else (s - elapsed) / length
                pos = a.lerp(b, ratio)
                tangent = (b - a).normalized()
                normal = Vector((-tangent.y, tangent.x, 0.0))
                return pos, tangent, normal
            elapsed += length
        tangent = (self.points[-1] - self.points[-2]).normalized()
        return self.points[-1], tangent, Vector((-tangent.y, tangent.x, 0.0))


def inside_xy(pos: Vector, bounds: tuple[float, float, float, float, float, float]) -> bool:
    min_x, max_x, min_y, max_y, _, _ = bounds
    return min_x <= pos.x <= max_x and min_y <= pos.y <= max_y


def find_mountain_interval(path: LoopPath, mountain: bpy.types.Object) -> tuple[float, float]:
    mb = bbox(mountain)
    step = 2.0
    intervals = []
    active_start = None
    s = 0.0
    while s <= path.total:
        pos, _, _ = path.sample(s)
        hit = inside_xy(pos, mb)
        if hit and active_start is None:
            active_start = s
        if not hit and active_start is not None:
            intervals.append((active_start, s - step))
            active_start = None
        s += step
    if active_start is not None:
        intervals.append((active_start, path.total))
    if not intervals:
        raise RuntimeError("Could not find a railway interval overlapping Mountain_Granite.")
    return max(intervals, key=lambda item: item[1] - item[0])


def add_box(name: str, loc: Vector, dims: tuple[float, float, float], yaw: float, mat, bsdf: str, col) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=loc, rotation=(0.0, 0.0, yaw))
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dims
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    assign(obj, mat, bsdf)
    link_to(obj, col)
    return obj


def yaw(tangent: Vector) -> float:
    return math.atan2(tangent.y, tangent.x)


def boolean_cut_mountain(mountain: bpy.types.Object, cutter: bpy.types.Object) -> bool:
    bpy.context.view_layer.objects.active = mountain
    mountain.select_set(True)
    mod = mountain.modifiers.new("RT_Tunnel_Boolean_Cut", "BOOLEAN")
    mod.operation = "DIFFERENCE"
    mod.object = cutter
    try:
        bpy.ops.object.modifier_apply(modifier=mod.name)
        return True
    except Exception:
        mountain.modifiers.remove(mod)
        return False
    finally:
        mountain.select_set(False)


def write_report(path: Path, data: dict) -> None:
    lines = [
        "# Tunnel-Only Scene Adjustment",
        "",
        f"- Source blend: `{data['source']}`",
        f"- Output blend: `{data['output']}`",
        f"- Loop length: {data['loop_length_m']:.3f} m",
        f"- Mountain-overlap tunnel interval: s={data['tunnel_s0_m']:.3f} to {data['tunnel_s1_m']:.3f} m",
        f"- Tunnel length: {data['tunnel_length_m']:.3f} m",
        f"- Tunnel width x height: {data['tunnel_width_m']:.2f} m x {data['tunnel_height_m']:.2f} m",
        f"- Boolean cut applied to Mountain_Granite: {data['boolean_cut_applied']}",
        f"- Tunnel objects added: {data['tunnel_objects_added']}",
        "",
        "## What Was Changed",
        "",
        "- Kept the existing map objects; no rice fields, houses, vegetation, roofs, bridges, rocks, or stations were duplicated.",
        "- Added only physical tunnel geometry: floor, ceiling, left/right walls, entry/exit portals.",
        "- Carved a tunnel volume out of `Mountain_Granite` using a Boolean difference on the copied working blend.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    bpy.ops.wm.open_mainfile(filepath=str(Path(args.source).resolve()))
    rail = bpy.data.objects.get("Railway")
    mountain = bpy.data.objects.get("Mountain_Granite")
    if rail is None or mountain is None:
        raise RuntimeError("Required objects Railway and/or Mountain_Granite were not found.")

    col = clean_collection("RT_Tunnel_Only_Zone_C")
    concrete = material("RT_Tunnel_Concrete", (0.52, 0.52, 0.50, 1.0), "mat-vn_concrete")
    granite = material("RT_Tunnel_Portal_Granite", (0.42, 0.43, 0.45, 1.0), "mat-vn_granite")

    path = LoopPath(rail)
    s0, s1 = find_mountain_interval(path, mountain)
    s0 = max(0.0, s0 - 15.0)
    s1 = min(path.total, s1 + 15.0)
    mid, tangent, normal = path.sample((s0 + s1) / 2.0)
    tunnel_len = s1 - s0
    tunnel_yaw = yaw(tangent)
    floor_z = 0.0
    height = args.tunnel_height_m
    width = args.tunnel_width_m

    cutter = add_box(
        "RT_Tunnel_Cutter_DoNotExport",
        Vector((mid.x, mid.y, floor_z + height / 2.0)),
        (tunnel_len + 12.0, width + 2.5, height + 2.5),
        tunnel_yaw,
        concrete,
        "mat-vn_concrete",
        col,
    )
    cutter.hide_render = True
    cutter.hide_viewport = True
    cut_ok = boolean_cut_mountain(mountain, cutter)
    bpy.data.objects.remove(cutter, do_unlink=True)

    added = 0
    s = s0
    idx = 0
    while s < s1 - 1e-6:
        e = min(s + args.segment_m, s1)
        seg_mid, seg_tangent, seg_normal = path.sample((s + e) / 2.0)
        seg_yaw = yaw(seg_tangent)
        seg_len = e - s
        add_box(f"RT_Tunnel_Floor_{idx:03d}", Vector((seg_mid.x, seg_mid.y, floor_z - 0.15)), (seg_len, width, 0.30), seg_yaw, concrete, "mat-vn_concrete", col)
        add_box(f"RT_Tunnel_Ceiling_{idx:03d}", Vector((seg_mid.x, seg_mid.y, floor_z + height)), (seg_len, width, 0.35), seg_yaw, concrete, "mat-vn_concrete", col)
        left = seg_mid + seg_normal * (width / 2.0)
        right = seg_mid - seg_normal * (width / 2.0)
        add_box(f"RT_Tunnel_Wall_Left_{idx:03d}", Vector((left.x, left.y, floor_z + height / 2.0)), (seg_len, 0.35, height), seg_yaw, concrete, "mat-vn_concrete", col)
        add_box(f"RT_Tunnel_Wall_Right_{idx:03d}", Vector((right.x, right.y, floor_z + height / 2.0)), (seg_len, 0.35, height), seg_yaw, concrete, "mat-vn_concrete", col)
        added += 4
        idx += 1
        s = e

    for label, s in (("Entry", s0), ("Exit", s1)):
        pos, t, _ = path.sample(s)
        add_box(f"RT_Tunnel_Portal_{label}", Vector((pos.x, pos.y, floor_z + height / 2.0)), (1.2, width + 3.0, height + 1.2), yaw(t), granite, "mat-vn_granite", col)
        added += 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out))
    report = {
        "source": str(Path(args.source).resolve()),
        "output": str(out.resolve()),
        "loop_length_m": path.total,
        "tunnel_s0_m": s0,
        "tunnel_s1_m": s1,
        "tunnel_length_m": tunnel_len,
        "tunnel_width_m": width,
        "tunnel_height_m": height,
        "boolean_cut_applied": cut_ok,
        "tunnel_objects_added": added,
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_report(report_path, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
