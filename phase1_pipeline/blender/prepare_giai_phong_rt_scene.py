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


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = argv[1:]
    parser = argparse.ArgumentParser(description="Prepare the Giai Phong - Giap Bat OSM scene for Sionna RT.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--rail-name", default="Đường sắt Bắc–Nam")
    parser.add_argument("--sample-spacing-m", type=float, default=25.0)
    return parser.parse_args(argv)


def make_material(name: str, color: tuple[float, float, float, float], bsdf_id: str) -> bpy.types.Material:
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.diffuse_color = color
    material["sionna_bsdf_id"] = bsdf_id
    material["mitsuba_bsdf_id"] = bsdf_id
    return material


def parent_names(obj: bpy.types.Object) -> list[str]:
    names = []
    parent = obj.parent
    while parent is not None:
        names.append(parent.name.lower())
        parent = parent.parent
    return names


def assign_rt_materials(materials: dict[str, bpy.types.Material], rail_name: str) -> None:
    for obj in bpy.data.objects:
        if obj.type not in {"MESH", "CURVE"}:
            continue
        text = " ".join([obj.name.lower(), obj.data.name.lower() if obj.data else "", *parent_names(obj)])
        if obj.name == rail_name or "railway" in text or "railways" in text or "đường sắt" in text:
            material = materials["rail"]
            obj["sionna_bsdf_id"] = "mat-vn_metal"
        elif "water" in text or "sông" in text or "lake" in text:
            material = materials["water"]
            obj["sionna_bsdf_id"] = "mat-vn_wet_ground"
        elif "building" in text or "osm_buildings" in text:
            material = materials["building"]
            obj["sionna_bsdf_id"] = "mat-vn_concrete"
        elif "forest" in text or "tree" in text or "vegetation" in text:
            material = materials["vegetation"]
            obj["sionna_bsdf_id"] = "mat-vn_vegetation"
        elif "road" in text or "highway" in text or "đường" in text:
            material = materials["road"]
            obj["sionna_bsdf_id"] = "mat-vn_concrete_rough"
        else:
            material = materials["default"]
            obj["sionna_bsdf_id"] = "mat-vn_concrete"
        obj.data.materials.clear()
        obj.data.materials.append(material)


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
            bezier_points = list(spline.bezier_points)
            for point in bezier_points:
                points.append(obj.matrix_world @ point.co)
        if len(points) >= 2:
            polylines.append(points)
    if not polylines:
        raise ValueError(f"No usable polyline found in curve {obj.name}.")
    return max(polylines, key=polyline_length)


def polyline_length(points: list[Vector]) -> float:
    return sum((points[idx] - points[idx - 1]).length for idx in range(1, len(points)))


def resample_polyline(points: list[Vector], spacing_m: float) -> tuple[list[Vector], list[Vector]]:
    total = polyline_length(points)
    count = max(2, int(math.ceil(total / spacing_m)) + 1)
    distances = [min(total, idx * spacing_m) for idx in range(count)]
    if distances[-1] < total:
        distances.append(total)
    samples: list[Vector] = []
    tangents: list[Vector] = []
    segment_idx = 1
    traversed = 0.0
    for target in distances:
        while segment_idx < len(points):
            segment = points[segment_idx] - points[segment_idx - 1]
            segment_len = segment.length
            if traversed + segment_len >= target or segment_idx == len(points) - 1:
                break
            traversed += segment_len
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


def nearest_cardinal_facing(direction: Vector) -> str:
    if abs(direction.x) >= abs(direction.y):
        return "x+" if direction.x >= 0.0 else "x-"
    return "y+" if direction.y >= 0.0 else "y-"


def point_at_fraction(samples: list[Vector], tangents: list[Vector], fraction: float) -> tuple[Vector, Vector]:
    index = max(0, min(len(samples) - 1, int(round((len(samples) - 1) * fraction))))
    return samples[index], tangents[index]


def create_rt_additions(samples: list[Vector], tangents: list[Vector], materials: dict[str, bpy.types.Material]) -> dict:
    gauge_m = 1.0
    rail_offset = gauge_m / 2.0
    left_rail = [center + lateral(tangent) * rail_offset for center, tangent in zip(samples, tangents)]
    right_rail = [center - lateral(tangent) * rail_offset for center, tangent in zip(samples, tangents)]
    add_curve("RT_Rail_Left_meter_gauge", left_rail, materials["highlight_rail"], 0.045, 0.16)
    add_curve("RT_Rail_Right_meter_gauge", right_rail, materials["highlight_rail"], 0.045, 0.16)
    add_curve("RT_Trajectory_Centerline", samples, materials["centerline"], 0.035, 0.32)
    build_ballast_mesh("RT_Ballast_Trackbed_4m", samples, tangents, 4.0, materials["ballast"])

    for idx in range(0, len(samples), 1):
        if idx % 1 != 0:
            continue
        center = samples[idx]
        tangent = tangents[idx]
        yaw = math.atan2(tangent.y, tangent.x) + math.pi / 2.0
        add_box(
            f"RT_Sleeper_{idx:03d}",
            Vector((center.x, center.y, 0.08)),
            (2.3, 0.22, 0.14),
            yaw,
            materials["sleeper"],
            "mat-vn_concrete_rough",
        )

    train_center, train_tangent = point_at_fraction(samples, tangents, 0.50)
    train_yaw = math.atan2(train_tangent.y, train_tangent.x)
    train_obj = add_box(
        "Train_Static_RT_Body",
        Vector((train_center.x, train_center.y, 2.15)),
        (25.0, 3.4, 4.3),
        train_yaw,
        materials["train"],
        "mat-vn_metal",
    )

    gnb_specs = [
        ("GNB_A", 0.14, -58.0, 30.0),
        ("GNB_B", 0.36, 62.0, 30.0),
        ("GNB_C", 0.61, -68.0, 30.0),
        ("GNB_D", 0.84, 64.0, 30.0),
    ]
    gnb_positions = []
    gnb_facing = []
    for name, fraction, offset_m, height_m in gnb_specs:
        center, tangent = point_at_fraction(samples, tangents, fraction)
        side = lateral(tangent)
        base = center + side * offset_m
        mast_center = Vector((base.x, base.y, height_m / 2.0))
        add_cylinder(f"{name}_Mast", mast_center, 0.22, height_m, materials["gnb"], "mat-vn_metal")
        to_track = Vector((center.x - base.x, center.y - base.y, 0.0)).normalized()
        antenna_yaw = math.atan2(to_track.y, to_track.x)
        antenna_center = Vector((base.x, base.y, height_m))
        add_box(f"{name}_Antenna", antenna_center, (0.9, 0.28, 1.35), antenna_yaw, materials["gnb"], "mat-vn_metal")
        gnb_positions.append([base.x, base.y, height_m])
        gnb_facing.append(nearest_cardinal_facing(to_track))

    return {
        "gauge_m": gauge_m,
        "all_gnb_positions_m": gnb_positions,
        "all_gnb_facing": gnb_facing,
        "train_static_position_m": [train_obj.location.x, train_obj.location.y, train_obj.location.z],
    }


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    output_paths = resolve_output_paths(config)
    output_paths["blend_file"].parent.mkdir(parents=True, exist_ok=True)
    rail_obj = bpy.data.objects.get(args.rail_name)
    if rail_obj is None:
        rail_candidates = [obj for obj in bpy.data.objects if obj.type == "CURVE" and "sắt" in obj.name.lower()]
        if not rail_candidates:
            raise KeyError(f"Rail curve not found: {args.rail_name}")
        rail_obj = max(rail_candidates, key=lambda obj: polyline_length(curve_polyline_points(obj)))

    materials = {
        "default": make_material("RT_Default_Concrete", (0.55, 0.55, 0.52, 1.0), "mat-vn_concrete"),
        "building": make_material("RT_Building_Concrete", (0.62, 0.64, 0.66, 1.0), "mat-vn_concrete"),
        "road": make_material("RT_Road_Rough_Concrete", (0.28, 0.29, 0.30, 1.0), "mat-vn_concrete_rough"),
        "water": make_material("RT_Wet_Ground_Water", (0.18, 0.36, 0.55, 1.0), "mat-vn_wet_ground"),
        "vegetation": make_material("RT_Vegetation", (0.20, 0.43, 0.20, 1.0), "mat-vn_vegetation"),
        "rail": make_material("RT_OSM_Rail_Metal", (0.08, 0.08, 0.08, 1.0), "mat-vn_metal"),
        "highlight_rail": make_material("RT_Highlight_Rail_Red", (1.0, 0.03, 0.02, 1.0), "mat-vn_metal"),
        "centerline": make_material("RT_Centerline_Yellow", (1.0, 0.85, 0.05, 1.0), "mat-vn_concrete_rough"),
        "ballast": make_material("RT_Ballast_Dark", (0.20, 0.20, 0.18, 1.0), "mat-vn_granite"),
        "sleeper": make_material("RT_Sleeper_Concrete", (0.78, 0.72, 0.58, 1.0), "mat-vn_concrete_rough"),
        "train": make_material("Train_Metal", (0.10, 0.14, 0.18, 1.0), "mat-vn_metal"),
        "gnb": make_material("GNB_Metal_Blue", (0.03, 0.20, 0.95, 1.0), "mat-vn_metal"),
    }
    assign_rt_materials(materials, rail_obj.name)

    source_points = curve_polyline_points(rail_obj)
    total_length_m = polyline_length(source_points)
    samples, tangents = resample_polyline(source_points, args.sample_spacing_m)
    additions = create_rt_additions(samples, tangents, materials)
    rx_height = float(config.get("train", {}).get("receiver_height_m", 4.2))
    metadata = {
        "scene_type": "giai_phong_giap_bat_osm_rt",
        "source_blend": bpy.data.filepath,
        "prepared_blend": str(output_paths["blend_file"]),
        "rail_object_name": rail_obj.name,
        "trajectory_method": f"blosm_curve:{rail_obj.name}",
        "track_length_m": total_length_m,
        "sample_spacing_m": args.sample_spacing_m,
        "rx_trajectory_samples": [[point.x, point.y, rx_height] for point in samples],
        **additions,
    }
    output_paths["scene_metadata"].write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    report_path = output_paths["blend_file"].with_suffix(".report.json")
    report_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    bpy.ops.wm.save_as_mainfile(filepath=str(output_paths["blend_file"]))
    print(f"Prepared Giai Phong RT scene: {output_paths['blend_file']}")
    print(f"Rail object: {rail_obj.name}")
    print(f"Track length: {total_length_m:.2f} m; RX samples: {len(samples)}")


if __name__ == "__main__":
    main()
