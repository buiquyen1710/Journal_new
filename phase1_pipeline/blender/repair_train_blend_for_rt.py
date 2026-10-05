from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


TRACK_KEYWORDS = ("railway", "rail", "track", "nurbspath", "catenary")
DROP_KEYWORDS = ("camera", "light")
GNB_KEYWORDS = ("gnb", "tx", "antenna")


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1 :] if "--" in argv else argv[1:]
    parser = argparse.ArgumentParser(description="Repair Train.blend for railway RT.")
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--target-loop-m", type=float, default=3200.0)
    parser.add_argument("--min-final-area-m2", type=float, default=7.0)
    parser.add_argument("--gnb-height-m", type=float, default=25.0)
    parser.add_argument("--corner-margin-m", type=float, default=25.0)
    return parser.parse_args(argv)


def safe_material(name: str, color: tuple[float, float, float, float], metallic: float = 0.0) -> bpy.types.Material:
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Metallic"].default_value = metallic
        bsdf.inputs["Roughness"].default_value = 0.45
    return mat


def text_for(obj: bpy.types.Object) -> str:
    return " ".join(
        part.lower()
        for part in (
            obj.name,
            obj.data.name if getattr(obj, "data", None) else "",
            obj.active_material.name if obj.active_material else "",
        )
    )


def is_track_like(obj: bpy.types.Object) -> bool:
    return any(keyword in text_for(obj) for keyword in TRACK_KEYWORDS)


def is_gnb_like(obj: bpy.types.Object) -> bool:
    return any(keyword in text_for(obj) for keyword in GNB_KEYWORDS)


def world_bbox(obj: bpy.types.Object) -> list[Vector]:
    return [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]


def xy_bounds(objects: list[bpy.types.Object]) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for obj in objects:
        for point in world_bbox(obj):
            xs.append(point.x)
            ys.append(point.y)
    if not xs:
        return (-1.0, 1.0, -1.0, 1.0)
    return (min(xs), max(xs), min(ys), max(ys))


def estimate_loop_length(bounds: tuple[float, float, float, float]) -> float:
    min_x, max_x, min_y, max_y = bounds
    return 2.0 * ((max_x - min_x) + (max_y - min_y))


def mesh_surface_area(obj: bpy.types.Object) -> float:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        if not mesh.polygons:
            return 0.0
        area = 0.0
        verts = mesh.vertices
        for poly in mesh.polygons:
            if len(poly.vertices) < 3:
                continue
            p0 = obj.matrix_world @ verts[poly.vertices[0]].co
            for idx in range(1, len(poly.vertices) - 1):
                p1 = obj.matrix_world @ verts[poly.vertices[idx]].co
                p2 = obj.matrix_world @ verts[poly.vertices[idx + 1]].co
                area += 0.5 * (p1 - p0).cross(p2 - p0).length
        return float(area)
    finally:
        evaluated.to_mesh_clear()


def scale_roots(factor: float) -> None:
    for obj in bpy.context.scene.objects:
        if obj.parent is None:
            obj.location *= factor
            obj.scale *= factor
    bpy.context.view_layer.update()


def apply_mesh_transforms() -> None:
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH" and obj.data.users > 1:
            obj.data = obj.data.copy()
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH":
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)


def bbox_dims(obj: bpy.types.Object) -> tuple[float, float, float]:
    corners = world_bbox(obj)
    xs = [p.x for p in corners]
    ys = [p.y for p in corners]
    zs = [p.z for p in corners]
    return (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))


def normalize_local_proportions() -> list[dict]:
    changes = []
    for obj in list(bpy.context.scene.objects):
        if obj.type != "MESH" or is_track_like(obj):
            continue
        text = text_for(obj)
        dx, dy, dz = bbox_dims(obj)
        max_xy = max(dx, dy, 1e-6)
        factor = None
        reason = ""
        if "station" in text:
            factor = min(1.0, 18.0 / max(dz, 1e-6))
            reason = "station height capped at about 18 m"
        elif obj.name.lower().startswith("cube") and max(dx, dy, dz) > 200.0:
            changes.append({"name": obj.name, "action": "removed", "reason": "generic cube was physically unrealistic after global scale"})
            bpy.data.objects.remove(obj, do_unlink=True)
            continue
        elif "train" in text:
            factor = 25.0 / max_xy
            reason = "train length normalized to about 25 m"
        elif "bamboo" in text:
            factor = 12.0 / max(dz, 1e-6)
            reason = "bamboo height normalized to about 12 m"
        elif "coconut" in text:
            factor = 18.0 / max(dz, 1e-6)
            reason = "coconut height normalized to about 18 m"
        elif any(key in text for key in ("tree", "forest", "fruit")):
            factor = 12.0 / max(dz, 1e-6)
            reason = "tree height normalized to about 12 m"
        elif any(key in text for key in ("electric_pole", "pole")) and max(dx, dy) > 250.0:
            changes.append({"name": obj.name, "action": "removed", "reason": "elongated pole asset was physically unrealistic after global scale"})
            bpy.data.objects.remove(obj, do_unlink=True)
            continue

        if factor is None or factor <= 0.0:
            continue
        if abs(factor - 1.0) < 1e-3:
            continue
        obj.scale *= factor
        changes.append({"name": obj.name, "action": "scaled", "factor": factor, "reason": reason})
    bpy.context.view_layer.update()
    apply_mesh_transforms()
    return changes


def remove_old_gnbs() -> list[str]:
    removed = []
    for obj in list(bpy.context.scene.objects):
        if obj.type == "MESH" and is_gnb_like(obj):
            removed.append(obj.name)
            bpy.data.objects.remove(obj, do_unlink=True)
    return removed


def assign_material_tags() -> None:
    mats = {
        "metal": safe_material("RT_Metal", (0.55, 0.57, 0.60, 1.0), 0.9),
        "concrete": safe_material("RT_Concrete", (0.58, 0.58, 0.55, 1.0)),
        "ground": safe_material("RT_Ground", (0.30, 0.38, 0.25, 1.0)),
        "vegetation": safe_material("RT_Vegetation", (0.20, 0.42, 0.18, 1.0)),
        "water": safe_material("RT_WetGround", (0.20, 0.30, 0.36, 1.0)),
        "granite": safe_material("RT_Granite", (0.46, 0.47, 0.48, 1.0)),
    }
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        text = text_for(obj)
        if any(k in text for k in ("rail", "wire", "catenary", "pole", "metal", "train", "gnb", "antenna")):
            obj.data.materials.clear()
            obj.data.materials.append(mats["metal"])
            obj["sionna_bsdf_id"] = "mat-vn_metal"
        elif any(k in text for k in ("tree", "bamboo", "coconut", "forest", "fruit")):
            obj.data.materials.clear()
            obj.data.materials.append(mats["vegetation"])
            obj["sionna_bsdf_id"] = "mat-vn_vegetation"
        elif any(k in text for k in ("river", "lake", "wet")):
            obj.data.materials.clear()
            obj.data.materials.append(mats["water"])
            obj["sionna_bsdf_id"] = "mat-vn_wet_ground"
        elif any(k in text for k in ("mountain", "rock", "granite")):
            obj.data.materials.clear()
            obj.data.materials.append(mats["granite"])
            obj["sionna_bsdf_id"] = "mat-vn_granite"
        elif any(k in text for k in ("land", "field", "ground")):
            obj.data.materials.clear()
            obj.data.materials.append(mats["ground"])
            obj["sionna_bsdf_id"] = "mat-vn_concrete_rough"
        else:
            obj.data.materials.clear()
            obj.data.materials.append(mats["concrete"])
            obj["sionna_bsdf_id"] = "mat-vn_concrete"


def add_gnbs(bounds: tuple[float, float, float, float], height: float, margin: float) -> list[list[float]]:
    min_x, max_x, min_y, max_y = bounds
    positions = [
        [min_x - margin, min_y - margin, height],
        [max_x + margin, min_y - margin, height],
        [max_x + margin, max_y + margin, height],
        [min_x - margin, max_y + margin, height],
    ]
    labels = ("GNB_SW", "GNB_SE", "GNB_NE", "GNB_NW")
    for label, (x, y, z) in zip(labels, positions):
        bpy.ops.mesh.primitive_cylinder_add(radius=0.35, depth=z, vertices=24, location=(x, y, z / 2.0))
        mast = bpy.context.object
        mast.name = f"{label}_mast"
        mast["sionna_bsdf_id"] = "mat-vn_metal"
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x, y, z))
        ant = bpy.context.object
        ant.name = f"{label}_antenna"
        ant.dimensions = (1.2, 0.35, 1.8)
        ant["sionna_bsdf_id"] = "mat-vn_metal"
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return positions


def write_report(path: Path, report: dict) -> None:
    lines = [
        "# Repaired Train.blend for Ray Tracing",
        "",
        f"- Source: `{report['source']}`",
        f"- Output: `{report['output']}`",
        f"- Original estimated loop length: {report['original_loop_length_m']:.3f} m/model-units",
        f"- Target loop length: {report['target_loop_length_m']:.3f} m",
        f"- Applied uniform scale: {report['scale_factor']:.6f}",
        f"- Final estimated loop length: {report['final_loop_length_m']:.3f} m",
        f"- Removed objects with final area < {report['min_final_area_m2']:.3f} m^2: {len(report['removed_small_objects'])}",
        f"- Remaining mesh objects before new gNB markers: {report['remaining_mesh_objects_before_gnb']}",
        f"- Added gNB markers: {len(report['gnb_positions_m'])}",
        "",
        "## GNB Positions",
        "",
    ]
    for idx, pos in enumerate(report["gnb_positions_m"], start=1):
        lines.append(f"- GNB {idx}: [{pos[0]:.3f}, {pos[1]:.3f}, {pos[2]:.3f}] m")
    lines.extend(["", "## Removed Objects", ""])
    if report["removed_small_objects"]:
        for item in report["removed_small_objects"]:
            lines.append(f"- `{item['name']}`: final area {item['final_area_m2']:.3f} m^2")
    else:
        lines.append("- None.")
    lines.extend(["", "## Local Proportion Fixes", ""])
    if report.get("local_proportion_changes"):
        for item in report["local_proportion_changes"]:
            if item["action"] == "scaled":
                lines.append(f"- `{item['name']}`: scaled by {item['factor']:.6f}; {item['reason']}")
            else:
                lines.append(f"- `{item['name']}`: removed; {item['reason']}")
    else:
        lines.append("- None.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    bpy.ops.wm.open_mainfile(filepath=str(Path(args.source).resolve()))
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    for obj in list(scene.objects):
        if any(keyword in obj.name.lower() for keyword in DROP_KEYWORDS):
            bpy.data.objects.remove(obj, do_unlink=True)

    mesh_objects = [obj for obj in scene.objects if obj.type == "MESH"]
    track_objects = [obj for obj in mesh_objects if is_track_like(obj)]
    original_bounds = xy_bounds(track_objects or mesh_objects)
    original_length = estimate_loop_length(original_bounds)
    scale_factor = args.target_loop_m / max(original_length, 1e-6)
    scale_roots(scale_factor)
    apply_mesh_transforms()
    local_proportion_changes = normalize_local_proportions()
    bpy.context.view_layer.update()

    removed_old_gnbs = remove_old_gnbs()
    removed_small = []
    for obj in list(scene.objects):
        if obj.type != "MESH":
            continue
        if is_track_like(obj):
            continue
        final_area = mesh_surface_area(obj)
        if final_area < args.min_final_area_m2:
            removed_small.append({"name": obj.name, "final_area_m2": final_area})
            bpy.data.objects.remove(obj, do_unlink=True)

    assign_material_tags()
    remaining_mesh = [obj for obj in scene.objects if obj.type == "MESH"]
    final_track_objects = [obj for obj in remaining_mesh if is_track_like(obj)]
    final_bounds = xy_bounds(final_track_objects or remaining_mesh)
    final_length = estimate_loop_length(final_bounds)
    gnb_positions = add_gnbs(final_bounds, args.gnb_height_m, args.corner_margin_m)
    assign_material_tags()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out))

    report = {
        "source": str(Path(args.source).resolve()),
        "output": str(out.resolve()),
        "original_loop_length_m": original_length,
        "target_loop_length_m": args.target_loop_m,
        "scale_factor": scale_factor,
        "final_loop_length_m": final_length,
        "min_final_area_m2": args.min_final_area_m2,
        "removed_old_gnbs": removed_old_gnbs,
        "local_proportion_changes": local_proportion_changes,
        "removed_small_objects": removed_small,
        "remaining_mesh_objects_before_gnb": len(remaining_mesh),
        "gnb_positions_m": gnb_positions,
        "final_xy_bounds_m": list(final_bounds),
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_report(report_path, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
