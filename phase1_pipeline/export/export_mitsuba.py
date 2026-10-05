from __future__ import annotations

import argparse
import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import bmesh
import bpy

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phase1_pipeline.common import load_config, resolve_output_paths


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = argv[1:]
    parser = argparse.ArgumentParser(description="Export the current Blender scene to Mitsuba XML.")
    parser.add_argument(
        "--config",
        default=str(ROOT / "phase1_pipeline" / "config" / "config.yaml"),
        help="Path to the pipeline YAML configuration file.",
    )
    return parser.parse_args(argv)


def safe_name(name: str) -> str:
    sanitized = []
    for char in name:
        if char in ("_", "-") or ("0" <= char <= "9") or ("A" <= char <= "Z") or ("a" <= char <= "z"):
            sanitized.append(char)
        else:
            sanitized.append("_")
    return "".join(sanitized).strip("_") or "object"


def export_object_to_obj(obj: bpy.types.Object, mesh_path: Path):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.triangulate(bm, faces=list(bm.faces))
        bm.to_mesh(mesh)
        bm.free()

        mesh.calc_loop_triangles()
        if not mesh.loop_triangles:
            return None

        material = obj.active_material
        material_name = material.name if material else "Default"

        with mesh_path.open("w", encoding="utf-8") as handle:
            handle.write(f"o {safe_name(obj.name)}\n")
            handle.write(f"usemtl {safe_name(material_name)}\n")
            for vertex in mesh.vertices:
                world = obj.matrix_world @ vertex.co
                handle.write(f"v {world.x:.9f} {world.y:.9f} {world.z:.9f}\n")
            for vertex in mesh.vertices:
                normal = vertex.normal.normalized()
                handle.write(f"vn {normal.x:.9f} {normal.y:.9f} {normal.z:.9f}\n")
            for face in mesh.loop_triangles:
                indices = [index + 1 for index in face.vertices]
                handle.write("f " + " ".join(f"{idx}//{idx}" for idx in indices) + "\n")
    finally:
        evaluated.to_mesh_clear()
    return material_name


def material_ref_id(material: bpy.types.Material | None) -> str:
    if material is not None:
        custom = material.get("sionna_bsdf_id") or material.get("mitsuba_bsdf_id")
        if custom:
            return str(custom)
    if material is None:
        return "mat-vn_concrete"
    if material.name == "Ground":
        return "mat-vn_concrete_rough"
    if "Window" in material.name or "Glass" in material.name:
        return "mat-vn_glass"
    if "Train" in material.name:
        return "mat-vn_metal"
    bsdf_type = material.get("mitsuba_bsdf", "diffuse")
    if bsdf_type == "conductor":
        return "mat-vn_metal"
    return "mat-vn_concrete"


def material_bsdf(material: bpy.types.Material | None, bsdf_id: str) -> ET.Element:
    radio_materials = {
        "mat-vn_concrete": (5.31, 0.02, 0.300, 0.120, 0.150),
        "mat-vn_concrete_rough": (8.0, 0.005, 0.350, 0.250, 0.200),
        "mat-vn_metal": (1.0, 5.8e7, 0.010, 0.030, 0.050),
        "mat-vn_glass": (6.27, 0.004, 0.020, 0.020, 0.050),
        "mat-vn_granite": (7.0, 0.001, 0.400, 0.180, 0.150),
        "mat-vn_vegetation": (1.8, 0.003, 0.120, 0.350, 0.250),
        "mat-vn_wet_ground": (27.0, 0.1, 0.500, 0.180, 0.150),
        "mat-vn_laterite": (12.0, 0.01, 0.350, 0.220, 0.180),
    }
    if bsdf_id not in radio_materials:
        return ET.Element("bsdf", {"type": "diffuse", "id": bsdf_id})
    eps_r, sigma, thickness, scattering, xpd = radio_materials[bsdf_id]
    bsdf = ET.Element("bsdf", {"type": "radio-material", "id": bsdf_id})
    ET.SubElement(bsdf, "float", {"name": "relative_permittivity", "value": f"{eps_r:.6g}"})
    ET.SubElement(bsdf, "float", {"name": "conductivity", "value": f"{sigma:.6g}"})
    ET.SubElement(bsdf, "float", {"name": "thickness", "value": f"{thickness:.3f}"})
    ET.SubElement(bsdf, "float", {"name": "scattering_coefficient", "value": f"{scattering:.3f}"})
    ET.SubElement(bsdf, "float", {"name": "xpd_coefficient", "value": f"{xpd:.3f}"})
    return bsdf


def object_bbox_area_xy(obj: bpy.types.Object) -> float:
    if not obj.bound_box:
        return 0.0
    from mathutils import Vector

    world_corners = [obj.matrix_world @ Vector(item) for item in obj.bound_box]
    xs = [corner.x for corner in world_corners]
    ys = [corner.y for corner in world_corners]
    return max(0.0, max(xs) - min(xs)) * max(0.0, max(ys) - min(ys))


def object_bbox_center_xy(obj: bpy.types.Object) -> tuple[float, float]:
    if not obj.bound_box:
        return (float(obj.location.x), float(obj.location.y))
    from mathutils import Vector

    corners = [obj.matrix_world @ Vector(item) for item in obj.bound_box]
    return (
        sum(corner.x for corner in corners) / len(corners),
        sum(corner.y for corner in corners) / len(corners),
    )


def protected_rt_object(obj: bpy.types.Object) -> bool:
    return obj.name.startswith(("RT_Rail", "RT_Ground", "RT_Ballast", "RT_DEM", "GNB_"))


def load_corridor_samples(output_paths, export_cfg) -> list[tuple[float, float]]:
    margin = float(export_cfg.get("corridor_clip_margin_m", 0.0) or 0.0)
    if margin <= 0.0:
        return []
    metadata_path = output_paths.get("scene_metadata")
    if metadata_path is None or not metadata_path.exists():
        return []
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [(float(item[0]), float(item[1])) for item in metadata.get("rx_trajectory_samples", [])]


def nearest_sample_distance_xy(point: tuple[float, float], samples: list[tuple[float, float]]) -> float:
    if not samples:
        return 0.0
    x, y = point
    return min(math.hypot(x - sx, y - sy) for sx, sy in samples)


def build_scene_xml(output_paths, config) -> ET.ElementTree:
    mesh_dir = output_paths["mesh_dir"]
    xml_dir = output_paths["mitsuba_xml"].parent
    for old_mesh in mesh_dir.glob("*.obj"):
        old_mesh.unlink()
    root = ET.Element("scene", {"version": "3.0.0"})
    include_train_in_rt_scene = bool(config.get("ray_tracing", {}).get("include_train_in_rt_scene", False))

    integrator = ET.SubElement(root, "integrator", {"type": "path"})
    ET.SubElement(integrator, "integer", {"name": "max_depth", "value": "8"})

    sensor = ET.SubElement(root, "sensor", {"type": "perspective"})
    ET.SubElement(sensor, "float", {"name": "fov", "value": "45"})
    film = ET.SubElement(sensor, "film", {"type": "hdrfilm"})
    ET.SubElement(film, "integer", {"name": "width", "value": "800"})
    ET.SubElement(film, "integer", {"name": "height", "value": "450"})
    sampler = ET.SubElement(sensor, "sampler", {"type": "independent"})
    ET.SubElement(sampler, "integer", {"name": "sample_count", "value": "16"})

    emitter = ET.SubElement(root, "emitter", {"type": "constant"})
    ET.SubElement(emitter, "rgb", {"name": "radiance", "value": "0.25,0.25,0.25"})

    declared_bsdfs = set()
    export_cfg = config.get("export", {})
    skip_keywords = tuple(str(item).lower() for item in export_cfg.get("skip_object_keywords", []))
    skip_curve_objects = bool(export_cfg.get("skip_curve_objects", False))
    keep_curve_keywords = tuple(str(item).lower() for item in export_cfg.get("keep_curve_keywords", []))
    skip_area_below_m2 = float(export_cfg.get("skip_object_area_below_m2", 0.0) or 0.0)
    corridor_margin_m = float(export_cfg.get("corridor_clip_margin_m", 0.0) or 0.0)
    corridor_samples = load_corridor_samples(output_paths, export_cfg)
    max_obj_bytes = int(export_cfg.get("max_obj_file_bytes", 0) or 0)

    for obj in sorted(bpy.data.objects, key=lambda item: item.name):
        if obj.type not in {"MESH", "CURVE"}:
            continue
        if skip_curve_objects and obj.type == "CURVE":
            keep_text = " ".join(
                part.lower()
                for part in (
                    obj.name,
                    obj.data.name if getattr(obj, "data", None) else "",
                )
            )
            if not keep_curve_keywords or not any(keyword in keep_text for keyword in keep_curve_keywords):
                continue
        if not include_train_in_rt_scene and obj.name.lower().startswith("train"):
            continue
        obj_text = " ".join(
            part.lower()
            for part in (
                obj.name,
                obj.data.name if getattr(obj, "data", None) else "",
                obj.active_material.name if obj.active_material else "",
            )
        )
        if skip_keywords and any(keyword in obj_text for keyword in skip_keywords):
            continue
        if not protected_rt_object(obj):
            if skip_area_below_m2 > 0.0 and object_bbox_area_xy(obj) < skip_area_below_m2:
                continue
            if corridor_margin_m > 0.0 and corridor_samples:
                if nearest_sample_distance_xy(object_bbox_center_xy(obj), corridor_samples) > corridor_margin_m:
                    continue
        mesh_path = mesh_dir / f"{safe_name(obj.name)}.obj"
        material_name = export_object_to_obj(obj, mesh_path)
        if material_name is None:
            if mesh_path.exists():
                mesh_path.unlink()
            continue
        if max_obj_bytes > 0 and mesh_path.stat().st_size > max_obj_bytes:
            mesh_path.unlink(missing_ok=True)
            continue
        bsdf_id = str(obj.get("sionna_bsdf_id") or obj.get("mitsuba_bsdf_id") or material_ref_id(obj.active_material))
        if bsdf_id not in declared_bsdfs:
            root.append(material_bsdf(obj.active_material, bsdf_id))
            declared_bsdfs.add(bsdf_id)
        shape = ET.SubElement(root, "shape", {"type": "obj", "id": f"mesh-{safe_name(obj.name)}"})
        rel_mesh_path = mesh_path.relative_to(xml_dir)
        ET.SubElement(shape, "string", {"name": "filename", "value": rel_mesh_path.as_posix()})
        ET.SubElement(shape, "boolean", {"name": "face_normals", "value": "true"})
        ET.SubElement(shape, "ref", {"id": bsdf_id, "name": "bsdf"})

    return ET.ElementTree(root)


def indent(element: ET.Element, level: int = 0) -> None:
    prefix = "\n" + "  " * level
    if len(element):
        if not element.text or not element.text.strip():
            element.text = prefix + "  "
        for child in element:
            indent(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = prefix
    elif level and (not element.tail or not element.tail.strip()):
        element.tail = prefix


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    output_paths = resolve_output_paths(config)
    tree = build_scene_xml(output_paths, config)
    indent(tree.getroot())
    tree.write(output_paths["mitsuba_xml"], encoding="utf-8", xml_declaration=True)
    print(f"Exported Mitsuba XML to {output_paths['mitsuba_xml']}")


if __name__ == "__main__":
    main()
