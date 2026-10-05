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
    parser = argparse.ArgumentParser(description="Add a tunnel following the actual Railway mesh through Mountain_Granite.")
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--width", type=float, default=16.0)
    parser.add_argument("--height", type=float, default=11.0)
    parser.add_argument("--wall-thickness", type=float, default=0.6)
    parser.add_argument("--sample-step", type=float, default=18.0)
    return parser.parse_args(argv)


def make_mat(name: str, color, bsdf_id: str) -> bpy.types.Material:
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    node = mat.node_tree.nodes.get("Principled BSDF")
    if node:
        node.inputs["Base Color"].default_value = color
        node.inputs["Roughness"].default_value = 0.52
    mat["sionna_bsdf_id"] = bsdf_id
    return mat


def assign(obj: bpy.types.Object, mat: bpy.types.Material, bsdf_id: str) -> None:
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    obj["sionna_bsdf_id"] = bsdf_id


def clean_collection(name: str) -> bpy.types.Collection:
    col = bpy.data.collections.get(name)
    if col:
        for obj in list(col.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        return col
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


def point_in_xy(p: Vector, b: tuple[float, float, float, float, float, float], margin: float = 8.0) -> bool:
    min_x, max_x, min_y, max_y, _, _ = b
    return min_x - margin <= p.x <= max_x + margin and min_y - margin <= p.y <= max_y + margin


def railway_points_in_mountain(rail: bpy.types.Object, mountain: bpy.types.Object) -> list[Vector]:
    mb = bbox(mountain)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    ev = rail.evaluated_get(depsgraph)
    mesh = ev.to_mesh()
    try:
        pts = []
        seen = set()
        for v in mesh.vertices:
            p = rail.matrix_world @ v.co
            if point_in_xy(p, mb):
                key = (round(p.x, 1), round(p.y, 1))
                if key in seen:
                    continue
                seen.add(key)
                pts.append(Vector((p.x, p.y, 1.2)))
        return pts
    finally:
        ev.to_mesh_clear()


def principal_axis(points: list[Vector]) -> Vector:
    # 2D PCA closed form.
    mx = sum(p.x for p in points) / len(points)
    my = sum(p.y for p in points) / len(points)
    sxx = sum((p.x - mx) ** 2 for p in points)
    syy = sum((p.y - my) ** 2 for p in points)
    sxy = sum((p.x - mx) * (p.y - my) for p in points)
    angle = 0.5 * math.atan2(2 * sxy, sxx - syy)
    return Vector((math.cos(angle), math.sin(angle), 0.0)).normalized()


def centerline_from_points(points: list[Vector], sample_step: float) -> list[Vector]:
    axis = principal_axis(points)
    normal = Vector((-axis.y, axis.x, 0.0))
    projections = [(p.dot(axis), p.dot(normal), p) for p in points]
    min_u = min(u for u, _, _ in projections)
    max_u = max(u for u, _, _ in projections)
    samples: list[Vector] = []
    u = min_u
    window = max(sample_step * 0.8, 10.0)
    while u <= max_u:
        bucket = [(v, p.z) for pu, v, p in projections if abs(pu - u) <= window]
        if bucket:
            avg_v = sum(v for v, _ in bucket) / len(bucket)
            avg_z = max(1.2, sum(z for _, z in bucket) / len(bucket) + 0.3)
            samples.append(axis * u + normal * avg_v + Vector((0.0, 0.0, avg_z)))
        u += sample_step
    if len(samples) < 3:
        raise RuntimeError("Could not derive enough centerline samples from Railway mesh.")
    # Remove near-duplicates while preserving order.
    filtered = [samples[0]]
    for p in samples[1:]:
        if (p - filtered[-1]).length > sample_step * 0.35:
            filtered.append(p)
    return filtered


def add_box_between(name: str, a: Vector, b: Vector, center_offset: Vector, dims_yz: tuple[float, float], mat, bsdf: str, col) -> bpy.types.Object:
    mid = (a + b) * 0.5 + center_offset
    d = b - a
    length = max(0.1, math.hypot(d.x, d.y))
    yaw = math.atan2(d.y, d.x)
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=mid, rotation=(0.0, 0.0, yaw))
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = (length, dims_yz[0], dims_yz[1])
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    assign(obj, mat, bsdf)
    link_to(obj, col)
    return obj


def add_portal(name: str, p: Vector, tangent: Vector, width: float, height: float, mat, col) -> bpy.types.Object:
    yaw = math.atan2(tangent.y, tangent.x)
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=Vector((p.x, p.y, height / 2.0)), rotation=(0.0, 0.0, yaw))
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = (1.5, width + 4.0, height + 2.0)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    assign(obj, mat, "mat-vn_granite")
    link_to(obj, col)
    return obj


def add_cutter_boxes(centerline: list[Vector], width: float, height: float, col) -> list[bpy.types.Object]:
    mat = make_mat("RT_Tunnel_Cutter_Mat", (1.0, 0.0, 0.0, 0.25), "mat-vn_concrete")
    cutters = []
    for i, (a, b) in enumerate(zip(centerline, centerline[1:])):
        obj = add_box_between(
            f"RT_Tunnel_Cutter_{i:03d}",
            a,
            b,
            Vector((0.0, 0.0, height / 2.0)),
            (width + 2.5, height + 2.5),
            mat,
            "mat-vn_concrete",
            col,
        )
        obj.hide_viewport = True
        obj.hide_render = True
        cutters.append(obj)
    return cutters


def boolean_cut(mountain: bpy.types.Object, cutters: list[bpy.types.Object]) -> int:
    applied = 0
    bpy.context.view_layer.objects.active = mountain
    mountain.select_set(True)
    for cutter in cutters:
        mod = mountain.modifiers.new(f"RT_Tunnel_Cut_{applied:03d}", "BOOLEAN")
        mod.operation = "DIFFERENCE"
        mod.object = cutter
        try:
            bpy.context.view_layer.objects.active = mountain
            bpy.ops.object.modifier_apply(modifier=mod.name)
            applied += 1
        except Exception:
            try:
                mountain.modifiers.remove(mod)
            except Exception:
                pass
    mountain.select_set(False)
    return applied


def write_report(path: Path, payload: dict) -> None:
    lines = [
        "# Rail-Following Tunnel Adjustment",
        "",
        f"- Source blend: `{payload['source']}`",
        f"- Output blend: `{payload['output']}`",
        f"- Railway points used inside mountain: {payload['rail_points_in_mountain']}",
        f"- Centerline samples: {payload['centerline_samples']}",
        f"- Approx tunnel length: {payload['tunnel_length_m']:.3f} m",
        f"- Tunnel width x height: {payload['width_m']:.2f} x {payload['height_m']:.2f} m",
        f"- Boolean cutter segments applied: {payload['boolean_cuts_applied']}",
        "",
        "## Scope",
        "",
        "- Kept the existing map. No zone objects were duplicated.",
        "- Added only a tunnel that follows the actual `Railway` mesh through `Mountain_Granite`.",
        "- Tunnel is segmented so curved/diagonal rail portions are followed locally.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    bpy.ops.wm.open_mainfile(filepath=str(Path(args.source).resolve()))
    rail = bpy.data.objects.get("Railway")
    mountain = bpy.data.objects.get("Mountain_Granite")
    if rail is None or mountain is None:
        raise RuntimeError("Required objects Railway and Mountain_Granite were not found.")

    col = clean_collection("RT_Rail_Following_Tunnel")
    concrete = make_mat("RT_Tunnel_Concrete", (0.52, 0.52, 0.50, 1.0), "mat-vn_concrete")
    granite = make_mat("RT_Tunnel_Portal_Granite", (0.42, 0.43, 0.45, 1.0), "mat-vn_granite")
    points = railway_points_in_mountain(rail, mountain)
    centerline = centerline_from_points(points, args.sample_step)
    cutters = add_cutter_boxes(centerline, args.width, args.height, col)
    cuts = boolean_cut(mountain, cutters)
    for cutter in cutters:
        bpy.data.objects.remove(cutter, do_unlink=True)

    added = 0
    for i, (a, b) in enumerate(zip(centerline, centerline[1:])):
        d = b - a
        tangent = Vector((d.x, d.y, 0.0)).normalized()
        normal = Vector((-tangent.y, tangent.x, 0.0))
        wall_z = args.height / 2.0
        # Oversized enough for a 25m train, catenary, and Sionna receiver clearance.
        add_box_between(f"RT_Tunnel_Floor_{i:03d}", a, b, Vector((0, 0, -0.2)), (args.width, 0.4), concrete, "mat-vn_concrete", col)
        add_box_between(f"RT_Tunnel_Ceiling_{i:03d}", a, b, Vector((0, 0, args.height)), (args.width, 0.45), concrete, "mat-vn_concrete", col)
        add_box_between(f"RT_Tunnel_Wall_Left_{i:03d}", a, b, normal * (args.width / 2.0) + Vector((0, 0, wall_z)), (0.55, args.height), concrete, "mat-vn_concrete", col)
        add_box_between(f"RT_Tunnel_Wall_Right_{i:03d}", a, b, -normal * (args.width / 2.0) + Vector((0, 0, wall_z)), (0.55, args.height), concrete, "mat-vn_concrete", col)
        added += 4
    start_tangent = (centerline[1] - centerline[0]).normalized()
    end_tangent = (centerline[-1] - centerline[-2]).normalized()
    add_portal("RT_Tunnel_Portal_Entry", centerline[0], start_tangent, args.width, args.height, granite, col)
    add_portal("RT_Tunnel_Portal_Exit", centerline[-1], end_tangent, args.width, args.height, granite, col)
    added += 2

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out))
    length = sum((b - a).length for a, b in zip(centerline, centerline[1:]))
    payload = {
        "source": str(Path(args.source).resolve()),
        "output": str(out.resolve()),
        "rail_points_in_mountain": len(points),
        "centerline_samples": len(centerline),
        "tunnel_length_m": length,
        "width_m": args.width,
        "height_m": args.height,
        "boolean_cuts_applied": cuts,
        "tunnel_objects_added": added,
        "centerline": [[round(p.x, 3), round(p.y, 3), round(p.z, 3)] for p in centerline],
    }
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.with_suffix(".json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_report(report, payload)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
