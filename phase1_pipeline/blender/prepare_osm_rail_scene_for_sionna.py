from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phase1_pipeline.common import load_config, resolve_output_paths


TERRAIN_PROFILES = {
    "do_thi_day_dac": {"spacing": 520.0, "height": 30.0, "offset": 64.0, "max_gnb": 5},
    "do_thi_cau_song": {"spacing": 360.0, "height": 38.0, "offset": 45.0, "max_gnb": 6, "fraction_start": 0.04, "fraction_end": 0.96},
    "dong_bang_cong_nghiep": {"spacing": 720.0, "height": 25.0, "offset": 70.0, "max_gnb": 5},
    "do_thi_cang_bien": {"spacing": 560.0, "height": 30.0, "offset": 70.0, "max_gnb": 6},
    "dam_pha_ven_bien": {"spacing": 820.0, "height": 25.0, "offset": 80.0, "max_gnb": 5},
    "deo_nui_ven_bien": {"spacing": 520.0, "height": 38.0, "offset": 35.0, "max_gnb": 12, "fraction_start": 0.02, "fraction_end": 0.98},
}


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = argv[1:]
    parser = argparse.ArgumentParser(description="Prepare an OSM railway scene for Sionna RT.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--scene-id", required=True)
    parser.add_argument("--terrain-type", required=True)
    parser.add_argument("--rail-name", default="")
    parser.add_argument("--sample-spacing-m", type=float, default=25.0)
    parser.add_argument("--ground-margin-x-m", type=float, default=220.0)
    parser.add_argument("--ground-margin-y-m", type=float, default=180.0)
    return parser.parse_args(argv)


def make_material(name: str, color: tuple[float, float, float, float], bsdf_id: str) -> bpy.types.Material:
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.diffuse_color = color
    material["sionna_bsdf_id"] = bsdf_id
    material["mitsuba_bsdf_id"] = bsdf_id
    return material


def cleanup_previous_rt_objects() -> None:
    prefixes = ("RT_", "GNB_", "Train_Static_RT_Body")
    for obj in list(bpy.data.objects):
        if obj.name.startswith(prefixes):
            bpy.data.objects.remove(obj, do_unlink=True)


def parent_names(obj: bpy.types.Object) -> list[str]:
    names = []
    parent = obj.parent
    while parent is not None:
        names.append(parent.name.lower())
        parent = parent.parent
    return names


def assign_rt_materials(materials: dict[str, bpy.types.Material], rail_obj_name: str) -> None:
    for obj in bpy.data.objects:
        if obj.type not in {"MESH", "CURVE"}:
            continue
        text = " ".join([obj.name.lower(), obj.data.name.lower() if obj.data else "", *parent_names(obj)])
        if obj.name == rail_obj_name or "railway" in text or "railways" in text or "đường sắt" in text:
            material = materials["rail"]
            obj["sionna_bsdf_id"] = "mat-vn_metal"
        elif "water" in text or "sông" in text or "lake" in text or "ao" in text:
            material = materials["water"]
            obj["sionna_bsdf_id"] = "mat-vn_wet_ground"
        elif "forest" in text or "tree" in text or "vegetation" in text:
            material = materials["vegetation"]
            obj["sionna_bsdf_id"] = "mat-vn_vegetation"
        elif "road" in text or "highway" in text:
            material = materials["road"]
            obj["sionna_bsdf_id"] = "mat-vn_concrete_rough"
        else:
            material = materials["building"]
            obj["sionna_bsdf_id"] = "mat-vn_concrete"
        obj.data.materials.clear()
        obj.data.materials.append(material)


def polyline_length(points: list[Vector]) -> float:
    return sum((points[idx] - points[idx - 1]).length for idx in range(1, len(points)))


def curve_polyline_points(obj: bpy.types.Object) -> list[Vector]:
    if obj.type != "CURVE":
        raise TypeError(f"{obj.name} is {obj.type}, expected CURVE.")
    polylines: list[list[Vector]] = []
    for spline in obj.data.splines:
        points: list[Vector] = []
        if spline.type == "POLY":
            for point in spline.points:
                local = Vector((point.co.x / point.co.w, point.co.y / point.co.w, point.co.z / point.co.w))
                points.append(obj.matrix_world @ local)
        elif spline.type == "BEZIER":
            for point in spline.bezier_points:
                points.append(obj.matrix_world @ point.co)
        if len(points) >= 2:
            polylines.append(points)
    if not polylines:
        raise ValueError(f"No usable polyline in {obj.name}")
    return max(polylines, key=polyline_length)


def is_rail_candidate(obj: bpy.types.Object) -> bool:
    if obj.type != "CURVE" or obj.name.startswith("RT_"):
        return False
    text = " ".join([obj.name.lower(), obj.data.name.lower() if obj.data else "", *parent_names(obj)])
    return "rail" in text or "railway" in text or "đường sắt" in text or "sắt" in text


def find_rail_object(preferred_name: str) -> bpy.types.Object:
    if preferred_name:
        obj = bpy.data.objects.get(preferred_name)
        if obj is not None:
            return obj
    candidates = []
    for obj in bpy.data.objects:
        if not is_rail_candidate(obj):
            continue
        try:
            length = polyline_length(curve_polyline_points(obj))
        except Exception:
            continue
        candidates.append((length, obj))
    if not candidates:
        raise KeyError("No OSM railway curve found in scene.")
    return max(candidates, key=lambda item: item[0])[1]


def resample_polyline(points: list[Vector], spacing_m: float) -> tuple[list[Vector], list[Vector]]:
    total = polyline_length(points)
    distances = [min(total, idx * spacing_m) for idx in range(max(2, int(math.ceil(total / spacing_m)) + 1))]
    if distances[-1] < total:
        distances.append(total)
    samples: list[Vector] = []
    tangents: list[Vector] = []
    segment_idx = 1
    traversed = 0.0
    for target in distances:
        while segment_idx < len(points):
            segment = points[segment_idx] - points[segment_idx - 1]
            if traversed + segment.length >= target or segment_idx == len(points) - 1:
                break
            traversed += segment.length
            segment_idx += 1
        segment = points[segment_idx] - points[segment_idx - 1]
        segment_len = max(segment.length, 1e-9)
        alpha = max(0.0, min(1.0, (target - traversed) / segment_len))
        sample = points[segment_idx - 1].lerp(points[segment_idx], alpha)
        tangent = Vector((segment.x, segment.y, 0.0)).normalized()
        samples.append(Vector((sample.x, sample.y, 0.0)))
        tangents.append(tangent)
    return samples, tangents


def lateral(tangent: Vector) -> Vector:
    return Vector((-tangent.y, tangent.x, 0.0)).normalized()


def add_curve(name: str, points: list[Vector], material: bpy.types.Material, bevel_depth: float, z: float) -> bpy.types.Object:
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    curve.resolution_u = 2
    curve.bevel_depth = bevel_depth
    curve.bevel_resolution = 2
    spline = curve.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for point, coord in zip(spline.points, points):
        point.co = (coord.x, coord.y, z, 1.0)
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    obj["sionna_bsdf_id"] = material["sionna_bsdf_id"]
    return obj


def add_box(name: str, location: Vector, dimensions: tuple[float, float, float], yaw_rad: float, material: bpy.types.Material, bsdf_id: str) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    obj.rotation_euler[2] = yaw_rad
    obj.data.materials.append(material)
    obj["sionna_bsdf_id"] = bsdf_id
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return obj


def add_cylinder(name: str, location: Vector, radius: float, depth: float, material: bpy.types.Material, bsdf_id: str) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=radius, depth=depth, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(material)
    obj["sionna_bsdf_id"] = bsdf_id
    return obj


def build_ballast_mesh(name: str, centers: list[Vector], tangents: list[Vector], width_m: float, material: bpy.types.Material) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name)
    vertices = []
    faces = []
    for center, tangent in zip(centers, tangents):
        side = lateral(tangent) * (width_m / 2.0)
        vertices.append((center.x + side.x, center.y + side.y, -0.03))
        vertices.append((center.x - side.x, center.y - side.y, -0.03))
    for idx in range(len(centers) - 1):
        faces.append((idx * 2, idx * 2 + 1, idx * 2 + 3, idx * 2 + 2))
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    obj["sionna_bsdf_id"] = material["sionna_bsdf_id"]
    return obj


def add_ground(samples: list[Vector], materials: dict[str, bpy.types.Material], margin_x: float, margin_y: float) -> None:
    min_x = min(point.x for point in samples) - margin_x
    max_x = max(point.x for point in samples) + margin_x
    min_y = min(point.y for point in samples) - margin_y
    max_y = max(point.y for point in samples) + margin_y
    mesh = bpy.data.meshes.new("RT_Ground_Plane_Corridor_Mesh")
    mesh.from_pydata([(min_x, min_y, -0.08), (max_x, min_y, -0.08), (max_x, max_y, -0.08), (min_x, max_y, -0.08)], [], [(0, 1, 2, 3)])
    mesh.update()
    obj = bpy.data.objects.new("RT_Ground_Plane_Corridor", mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(materials["road"])
    obj["sionna_bsdf_id"] = "mat-vn_concrete_rough"


def nearest_cardinal_facing(direction: Vector) -> str:
    if abs(direction.x) >= abs(direction.y):
        return "x+" if direction.x >= 0.0 else "x-"
    return "y+" if direction.y >= 0.0 else "y-"


def point_at_fraction(samples: list[Vector], tangents: list[Vector], fraction: float) -> tuple[Vector, Vector]:
    index = max(0, min(len(samples) - 1, int(round((len(samples) - 1) * fraction))))
    return samples[index], tangents[index]


def gnb_fractions(count: int, profile: dict) -> list[float]:
    if count <= 1:
        return [0.5]
    start = float(profile.get("fraction_start", 0.12))
    end = float(profile.get("fraction_end", 0.88))
    return [start + (end - start) * idx / (count - 1) for idx in range(count)]


def create_rt_additions(samples: list[Vector], tangents: list[Vector], materials: dict[str, bpy.types.Material], terrain_type: str) -> dict:
    gauge_m = 1.0
    left_rail = [center + lateral(tangent) * (gauge_m / 2.0) for center, tangent in zip(samples, tangents)]
    right_rail = [center - lateral(tangent) * (gauge_m / 2.0) for center, tangent in zip(samples, tangents)]
    add_curve("RT_Rail_Left_meter_gauge", left_rail, materials["highlight_rail"], 0.045, 0.16)
    add_curve("RT_Rail_Right_meter_gauge", right_rail, materials["highlight_rail"], 0.045, 0.16)
    add_curve("RT_Trajectory_Centerline", samples, materials["centerline"], 0.035, 0.32)
    build_ballast_mesh("RT_Ballast_Trackbed_4m", samples, tangents, 4.0, materials["ballast"])
    add_ground(samples, materials, 220.0, 180.0)

    mid_center, mid_tangent = point_at_fraction(samples, tangents, 0.5)
    add_box("Train_Static_RT_Body", Vector((mid_center.x, mid_center.y, 2.15)), (25.0, 3.4, 4.3), math.atan2(mid_tangent.y, mid_tangent.x), materials["train"], "mat-vn_metal")

    profile = TERRAIN_PROFILES.get(terrain_type, TERRAIN_PROFILES["dong_bang_cong_nghiep"])
    track_length = max(1.0, sum((samples[idx] - samples[idx - 1]).length for idx in range(1, len(samples))))
    count = max(2, min(int(profile["max_gnb"]), int(math.ceil(track_length / float(profile["spacing"]))) + 1))
    gnb_positions = []
    gnb_facing = []
    for idx, fraction in enumerate(gnb_fractions(count, profile)):
        center, tangent = point_at_fraction(samples, tangents, fraction)
        side_sign = -1.0 if idx % 2 == 0 else 1.0
        offset = float(profile["offset"]) * side_sign
        side = lateral(tangent)
        base = center + side * offset
        height = float(profile["height"])
        add_cylinder(f"GNB_{chr(65 + idx)}_Mast", Vector((base.x, base.y, height / 2.0)), 0.22, height, materials["gnb"], "mat-vn_metal")
        to_track = Vector((center.x - base.x, center.y - base.y, 0.0)).normalized()
        add_box(f"GNB_{chr(65 + idx)}_Antenna", Vector((base.x, base.y, height)), (0.9, 0.28, 1.35), math.atan2(to_track.y, to_track.x), materials["gnb"], "mat-vn_metal")
        gnb_positions.append([base.x, base.y, height])
        gnb_facing.append(nearest_cardinal_facing(to_track))
    return {"gauge_m": gauge_m, "all_gnb_positions_m": gnb_positions, "all_gnb_facing": gnb_facing, "train_static_position_m": [mid_center.x, mid_center.y, 2.15]}


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    output_paths = resolve_output_paths(config)
    cleanup_previous_rt_objects()
    rail_obj = find_rail_object(args.rail_name)
    materials = {
        "building": make_material("RT_Building_Concrete", (0.62, 0.64, 0.66, 1.0), "mat-vn_concrete"),
        "road": make_material("RT_Road_Rough_Concrete", (0.36, 0.36, 0.34, 1.0), "mat-vn_concrete_rough"),
        "water": make_material("RT_Wet_Ground_Water", (0.18, 0.36, 0.55, 1.0), "mat-vn_wet_ground"),
        "vegetation": make_material("RT_Vegetation", (0.20, 0.43, 0.20, 1.0), "mat-vn_vegetation"),
        "rail": make_material("RT_OSM_Rail_Metal", (0.08, 0.08, 0.08, 1.0), "mat-vn_metal"),
        "highlight_rail": make_material("RT_Highlight_Rail_Red", (1.0, 0.03, 0.02, 1.0), "mat-vn_metal"),
        "centerline": make_material("RT_Centerline_Yellow", (1.0, 0.85, 0.05, 1.0), "mat-vn_concrete_rough"),
        "ballast": make_material("RT_Ballast_Dark", (0.20, 0.20, 0.18, 1.0), "mat-vn_granite"),
        "train": make_material("Train_Metal", (0.10, 0.14, 0.18, 1.0), "mat-vn_metal"),
        "gnb": make_material("GNB_Metal_Blue", (0.03, 0.20, 0.95, 1.0), "mat-vn_metal"),
    }
    assign_rt_materials(materials, rail_obj.name)
    source_points = curve_polyline_points(rail_obj)
    samples, tangents = resample_polyline(source_points, args.sample_spacing_m)
    additions = create_rt_additions(samples, tangents, materials, args.terrain_type)
    rx_height = float(config.get("train", {}).get("receiver_height_m", 4.2))
    metadata = {
        "scene_id": args.scene_id,
        "terrain_type": args.terrain_type,
        "source_blend": bpy.data.filepath,
        "prepared_blend": str(output_paths["blend_file"]),
        "rail_object_name": rail_obj.name,
        "trajectory_method": f"blosm_curve:{rail_obj.name}",
        "track_length_m": polyline_length(source_points),
        "sample_spacing_m": args.sample_spacing_m,
        "rx_trajectory_samples": [[point.x, point.y, rx_height] for point in samples],
        **additions,
    }
    output_paths["scene_metadata"].write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    output_paths["blend_file"].with_suffix(".report.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    bpy.ops.wm.save_as_mainfile(filepath=str(output_paths["blend_file"]))
    print(f"Prepared {args.scene_id}: rail={rail_obj.name}, length={metadata['track_length_m']:.2f} m, samples={len(samples)}, gNBs={len(additions['all_gnb_positions_m'])}")


if __name__ == "__main__":
    main()
