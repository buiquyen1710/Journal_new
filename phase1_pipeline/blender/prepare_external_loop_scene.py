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


TRACK_KEYWORDS = ("rail", "track", "duong_ray", "duongray", "ray", "sleeper")
GNB_KEYWORDS = ("gnb", "tx", "base", "antenna")


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1 :] if "--" in argv else argv[1:]
    parser = argparse.ArgumentParser(description="Prepare an external loop railway .blend for Sionna RT.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--source-blend", required=True)
    return parser.parse_args(argv)


def clean_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in value).strip("_") or "object"


def world_bbox(obj: bpy.types.Object) -> list[Vector]:
    return [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]


def bbox_area_proxy(obj: bpy.types.Object) -> float:
    corners = world_bbox(obj)
    xs = [p.x for p in corners]
    ys = [p.y for p in corners]
    zs = [p.z for p in corners]
    dx = max(xs) - min(xs)
    dy = max(ys) - min(ys)
    dz = max(zs) - min(zs)
    dims = sorted((abs(dx), abs(dy), abs(dz)), reverse=True)
    return dims[0] * dims[1]


def mesh_surface_area_m2(obj: bpy.types.Object) -> float:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        if not mesh.polygons:
            return 0.0
        area = 0.0
        vertices = mesh.vertices
        for poly in mesh.polygons:
            if len(poly.vertices) < 3:
                continue
            p0 = obj.matrix_world @ vertices[poly.vertices[0]].co
            for idx in range(1, len(poly.vertices) - 1):
                p1 = obj.matrix_world @ vertices[poly.vertices[idx]].co
                p2 = obj.matrix_world @ vertices[poly.vertices[idx + 1]].co
                area += 0.5 * (p1 - p0).cross(p2 - p0).length
        return float(area)
    finally:
        evaluated.to_mesh_clear()


def is_track_object(obj: bpy.types.Object) -> bool:
    text = " ".join(
        part.lower()
        for part in (
            obj.name,
            obj.data.name if getattr(obj, "data", None) else "",
            obj.active_material.name if obj.active_material else "",
        )
    )
    return any(keyword in text for keyword in TRACK_KEYWORDS)


def scene_xy_bounds(objects: list[bpy.types.Object]) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for obj in objects:
        for point in world_bbox(obj):
            xs.append(point.x)
            ys.append(point.y)
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), max(xs), min(ys), max(ys))


def estimate_loop_length_m(track_objects: list[bpy.types.Object], mesh_objects: list[bpy.types.Object]) -> tuple[float, str]:
    objects = track_objects or mesh_objects
    min_x, max_x, min_y, max_y = scene_xy_bounds(objects)
    width = max_x - min_x
    depth = max_y - min_y
    if width > 0.0 and depth > 0.0:
        return 2.0 * (width + depth), "xy_bbox_perimeter"
    return max(width, depth), "xy_bbox_longest_axis"


def scale_scene(factor: float) -> None:
    for obj in bpy.context.scene.objects:
        if obj.parent is None:
            obj.location *= factor
            obj.scale *= factor


def assign_basic_material_tags() -> None:
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        text = obj.name.lower()
        if any(key in text for key in ("rail", "wire", "gnb", "tx", "antenna", "pole", "metal")):
            obj["sionna_bsdf_id"] = "mat-vn_metal"
        elif any(key in text for key in ("tree", "leaf", "vegetation")):
            obj["sionna_bsdf_id"] = "mat-vn_vegetation"
        elif any(key in text for key in ("glass", "window")):
            obj["sionna_bsdf_id"] = "mat-vn_glass"
        elif any(key in text for key in ("water", "river", "canal")):
            obj["sionna_bsdf_id"] = "mat-vn_wet_ground"
        elif any(key in text for key in ("rock", "stone", "mountain")):
            obj["sionna_bsdf_id"] = "mat-vn_granite"
        else:
            obj["sionna_bsdf_id"] = "mat-vn_concrete"


def build_loop_trajectory(bounds: tuple[float, float, float, float], z_m: float, spacing_m: float) -> list[list[float]]:
    min_x, max_x, min_y, max_y = bounds
    corners = [(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y), (min_x, min_y)]
    samples: list[list[float]] = []
    for start, end in zip(corners, corners[1:]):
        sx, sy = start
        ex, ey = end
        distance = math.hypot(ex - sx, ey - sy)
        steps = max(1, int(math.ceil(distance / spacing_m)))
        for idx in range(steps):
            if samples and idx == 0:
                continue
            ratio = idx / steps
            samples.append([round(sx + (ex - sx) * ratio, 3), round(sy + (ey - sy) * ratio, 3), round(z_m, 3)])
    samples.append([round(corners[-1][0], 3), round(corners[-1][1], 3), round(z_m, 3)])
    return samples


def mesh_world_xy_points(obj: bpy.types.Object) -> list[Vector]:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        points: list[Vector] = []
        seen = set()
        for vertex in mesh.vertices:
            p = obj.matrix_world @ vertex.co
            key = (round(p.x, 1), round(p.y, 1))
            if key in seen:
                continue
            seen.add(key)
            points.append(Vector((p.x, p.y, 0.0)))
        return points
    finally:
        evaluated.to_mesh_clear()


def circular_mean_angle(angles: list[float]) -> float:
    sx = sum(math.cos(a) for a in angles)
    sy = sum(math.sin(a) for a in angles)
    return math.atan2(sy, sx)


def resample_closed_polyline(points: list[Vector], z_m: float, spacing_m: float) -> list[list[float]]:
    if len(points) < 4:
        return []
    closed = points + [points[0]]
    lengths = [(b - a).length for a, b in zip(closed, closed[1:])]
    total = sum(lengths)
    if total <= spacing_m:
        return []
    samples: list[list[float]] = []
    target = 0.0
    seg_start_dist = 0.0
    seg_idx = 0
    while target < total:
        while seg_idx < len(lengths) - 1 and seg_start_dist + lengths[seg_idx] < target:
            seg_start_dist += lengths[seg_idx]
            seg_idx += 1
        a, b = closed[seg_idx], closed[seg_idx + 1]
        seg_len = max(lengths[seg_idx], 1e-9)
        ratio = (target - seg_start_dist) / seg_len
        p = a.lerp(b, ratio)
        samples.append([round(p.x, 3), round(p.y, 3), round(z_m, 3)])
        target += spacing_m
    samples.append(samples[0])
    return samples


def resample_open_polyline(points: list[Vector], z_m: float, spacing_m: float) -> list[list[float]]:
    if len(points) < 2:
        return []
    lengths = [(b - a).length for a, b in zip(points, points[1:])]
    total = sum(lengths)
    if total <= 0.0:
        return []
    samples: list[list[float]] = []
    target = 0.0
    seg_start_dist = 0.0
    seg_idx = 0
    while target < total:
        while seg_idx < len(lengths) - 1 and seg_start_dist + lengths[seg_idx] < target:
            seg_start_dist += lengths[seg_idx]
            seg_idx += 1
        a, b = points[seg_idx], points[seg_idx + 1]
        seg_len = max(lengths[seg_idx], 1e-9)
        ratio = (target - seg_start_dist) / seg_len
        p = a.lerp(b, ratio)
        samples.append([round(p.x, 3), round(p.y, 3), round(z_m, 3)])
        target += spacing_m
    end = points[-1]
    samples.append([round(end.x, 3), round(end.y, 3), round(z_m, 3)])
    return samples


def build_rail_mesh_trajectory(track_objects: list[bpy.types.Object], z_m: float, spacing_m: float) -> tuple[list[list[float]], str]:
    explicit_centerline = bpy.data.objects.get("RT_Trajectory_Centerline")
    if explicit_centerline and explicit_centerline.type == "MESH":
        points = mesh_world_xy_points(explicit_centerline)
        if len(points) >= 4:
            # The authored centerline mesh stores vertices in path order.
            depsgraph = bpy.context.evaluated_depsgraph_get()
            evaluated = explicit_centerline.evaluated_get(depsgraph)
            mesh = evaluated.to_mesh()
            try:
                ordered = [explicit_centerline.matrix_world @ vertex.co for vertex in mesh.vertices]
                ordered = [Vector((p.x, p.y, 0.0)) for p in ordered]
            finally:
                evaluated.to_mesh_clear()
            if (ordered[0] - ordered[-1]).length < 1e-3:
                return resample_closed_polyline(ordered[:-1], z_m, spacing_m), "explicit_rt_trajectory_centerline_closed"
            return resample_open_polyline(ordered, z_m, spacing_m), "explicit_rt_trajectory_centerline_open"

    railway = [obj for obj in track_objects if obj.name.lower() == "railway"]
    source_objects = railway or track_objects
    points: list[Vector] = []
    for obj in source_objects:
        points.extend(mesh_world_xy_points(obj))
    if len(points) < 100:
        return [], "bbox_fallback_not_enough_rail_points"

    cx = sum(p.x for p in points) / len(points)
    cy = sum(p.y for p in points) / len(points)
    center = Vector((cx, cy, 0.0))
    radii = sorted((p - center).length for p in points)
    if not radii:
        return [], "bbox_fallback_no_rail_radius"
    # Keep the outer loop and drop small interior details/sidings that would pull the trajectory inward.
    radius_floor = radii[int(len(radii) * 0.55)]
    outer_points = [p for p in points if (p - center).length >= radius_floor]
    if len(outer_points) < 100:
        outer_points = points

    # Use angular bins around the scene center to derive a closed loop centerline.
    # This follows the existing loop geometry without duplicating zone objects.
    bins = max(72, min(720, int(len(outer_points) ** 0.5) * 8))
    buckets: list[list[Vector]] = [[] for _ in range(bins)]
    angle_buckets: list[list[float]] = [[] for _ in range(bins)]
    for p in outer_points:
        angle = math.atan2(p.y - cy, p.x - cx)
        idx = int(((angle + math.pi) / (2.0 * math.pi)) * bins) % bins
        buckets[idx].append(p)
        angle_buckets[idx].append(angle)

    loop_points: list[Vector] = []
    for bucket, angles in zip(buckets, angle_buckets):
        if not bucket:
            continue
        angle = circular_mean_angle(angles)
        radius = sum((p - center).length for p in bucket) / len(bucket)
        loop_points.append(Vector((cx + math.cos(angle) * radius, cy + math.sin(angle) * radius, 0.0)))
    if len(loop_points) < 12:
        return [], "bbox_fallback_sparse_angular_rail_bins"

    trajectory = resample_closed_polyline(loop_points, z_m, spacing_m)
    return trajectory, f"railway_mesh_angular_centerline:{','.join(obj.name for obj in source_objects[:3])}"


def corner_gnb_positions(config: dict, bounds: tuple[float, float, float, float]) -> list[list[float]]:
    scene_cfg = config.get("external_scene", {})
    if not bool(scene_cfg.get("place_gnbs_at_scene_corners", False)):
        return [list(map(float, station["position_m"])) for station in config.get("base_stations", [])]
    min_x, max_x, min_y, max_y = bounds
    margin = float(scene_cfg.get("gnb_corner_margin_m", 20.0))
    height = float(scene_cfg.get("gnb_height_m", 25.0))
    return [
        [min_x - margin, min_y - margin, height],
        [max_x + margin, min_y - margin, height],
        [max_x + margin, max_y + margin, height],
        [min_x - margin, max_y + margin, height],
    ]


def object_position_m(obj: bpy.types.Object) -> list[float]:
    corners = world_bbox(obj)
    xs = [point.x for point in corners]
    ys = [point.y for point in corners]
    zs = [point.z for point in corners]
    return [
        round(float((min(xs) + max(xs)) / 2.0), 3),
        round(float((min(ys) + max(ys)) / 2.0), 3),
        round(float((min(zs) + max(zs)) / 2.0), 3),
    ]


def scene_gnb_positions(config: dict) -> list[list[float]]:
    positions = corner_gnb_positions(config, (0.0, 0.0, 0.0, 0.0))
    mesh_objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    for idx, station in enumerate(config.get("base_stations", [])):
        station_name = clean_name(str(station.get("name", f"GNB{idx + 1}"))).lower()
        matches = [obj for obj in mesh_objects if station_name in obj.name.lower()]
        if not matches:
            continue
        antenna = [obj for obj in matches if "antenna" in obj.name.lower()]
        mast = [obj for obj in matches if "mast" in obj.name.lower()]
        source = (antenna or mast or matches)[0]
        position = object_position_m(source)
        if not antenna and mast:
            position[2] = round(float(source.dimensions.z), 3)
        positions[idx] = position
    return positions


def add_gnb_markers(config: dict, bounds: tuple[float, float, float, float], report: dict) -> None:
    removed_existing = []
    scene_cfg = config.get("external_scene", {})
    if bool(scene_cfg.get("read_gnb_positions_from_scene", True)) and not bool(scene_cfg.get("place_gnbs_at_scene_corners", False)):
        positions = scene_gnb_positions(config)
    else:
        positions = corner_gnb_positions(config, bounds)
    for obj in list(bpy.context.scene.objects):
        text = obj.name.lower()
        if obj.type == "MESH" and any(key in text for key in ("gnb", "tx", "antenna")):
            removed_existing.append(obj.name)
            bpy.data.objects.remove(obj, do_unlink=True)
    created = []
    for idx, position in enumerate(positions, start=1):
        x, y, z = position
        station = config.get("base_stations", [{}] * len(positions))[idx - 1]
        name = clean_name(str(station.get("name", f"GNB{idx}")))
        bpy.ops.mesh.primitive_cylinder_add(radius=0.25, depth=z, vertices=16, location=(x, y, z / 2.0))
        mast = bpy.context.object
        mast.name = f"{name}_mast"
        mast["sionna_bsdf_id"] = "mat-vn_metal"
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x, y, z))
        antenna = bpy.context.object
        antenna.name = f"{name}_antenna"
        antenna.dimensions = (0.8, 0.25, 1.2)
        antenna["sionna_bsdf_id"] = "mat-vn_metal"
        created.append([x, y, z])
    report["created_gnb_positions_m"] = created
    report["removed_existing_gnb_objects"] = removed_existing


def write_markdown_report(path: Path, report: dict) -> None:
    lines = [
        "# External Loop Scene Scale Report",
        "",
        f"- Source blend: `{report['source_blend']}`",
        f"- Prepared blend: `{report['prepared_blend']}`",
        f"- Estimated original loop length: {report['original_loop_length_m']:.3f} m ({report['length_estimation_method']})",
        f"- Target minimum loop length: {report['target_min_length_m']:.3f} m",
        f"- Applied uniform scale factor: {report['scale_factor']:.6f}",
        f"- Estimated final loop length: {report['final_loop_length_m']:.3f} m",
        f"- Trajectory method: `{report.get('trajectory_method', 'unknown')}`",
        f"- Trajectory samples: {report.get('trajectory_samples', 'unknown')}",
        f"- Removed mesh objects with surface area < {report['min_surface_area_m2']:.3f} m^2: {len(report['removed_small_objects'])}",
        f"- Remaining mesh objects: {report['remaining_mesh_objects']}",
        "",
        "## Scale Details",
        "",
    ]
    if report["scale_factor"] == 1.0:
        lines.append("- No scale was applied because the estimated loop length already satisfied the target.")
    else:
        lines.append(f"- Uniformly scaled all root objects by `{report['scale_factor']:.6f}` about the scene origin.")
        lines.append("- Object locations and object scale values were both multiplied by this factor.")
    lines.extend(["", "## Removed Objects", ""])
    if report["removed_small_objects"]:
        for item in report["removed_small_objects"][:200]:
            lines.append(f"- `{item['name']}`: {item['surface_area_m2']:.4f} m^2")
        if len(report["removed_small_objects"]) > 200:
            lines.append(f"- ... {len(report['removed_small_objects']) - 200} more omitted from this markdown summary.")
    else:
        lines.append("- None.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    output_paths = resolve_output_paths(config)
    scene_cfg = config.get("external_scene", {})
    source_blend = Path(args.source_blend).resolve()

    bpy.ops.wm.open_mainfile(filepath=str(source_blend))
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = 1.0

    mesh_objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    track_objects = [obj for obj in mesh_objects if is_track_object(obj)]
    original_length, method = estimate_loop_length_m(track_objects, mesh_objects)
    target_length = float(scene_cfg.get("target_min_track_length_m", 3000.0))
    scale_factor = 1.0 if original_length >= target_length else target_length / max(original_length, 1e-6)

    removed = []
    min_area = float(scene_cfg.get("remove_objects_below_area_m2", 7.0))
    keep_keywords = tuple(str(v).lower() for v in scene_cfg.get("small_object_keep_keywords", ["rail", "track", "gnb", "tx", "antenna"]))
    for obj in list(bpy.context.scene.objects):
        if obj.type != "MESH":
            continue
        if obj.name == "RT_Trajectory_Centerline":
            continue
        text = obj.name.lower()
        if any(keyword in text for keyword in keep_keywords):
            continue
        area = mesh_surface_area_m2(obj)
        if area < min_area:
            removed.append({"name": obj.name, "surface_area_m2": area})
            bpy.data.objects.remove(obj, do_unlink=True)

    if scale_factor != 1.0:
        scale_scene(scale_factor)
        bpy.context.view_layer.update()

    assign_basic_material_tags()
    bpy.context.view_layer.update()

    remaining_mesh = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    track_objects = [obj for obj in remaining_mesh if is_track_object(obj)]
    final_length, _ = estimate_loop_length_m(track_objects, remaining_mesh)
    bounds = scene_xy_bounds(track_objects or remaining_mesh)
    rx_z = float(config.get("train", {}).get("receiver_height_m", 4.2))
    spacing = float(scene_cfg.get("trajectory_spacing_m", 10.0))
    trajectory, trajectory_method = build_rail_mesh_trajectory(track_objects, rx_z, spacing)
    if not trajectory:
        trajectory_method = trajectory_method or "bbox_fallback"
        trajectory = build_loop_trajectory(bounds, rx_z, spacing)

    report = {
        "source_blend": str(source_blend),
        "prepared_blend": str(output_paths["blend_file"]),
        "original_loop_length_m": original_length,
        "final_loop_length_m": final_length,
        "target_min_length_m": target_length,
        "length_estimation_method": method,
        "scale_factor": scale_factor,
        "min_surface_area_m2": min_area,
        "removed_small_objects": removed,
        "remaining_mesh_objects": len(remaining_mesh),
        "trajectory_method": trajectory_method,
        "trajectory_samples": len(trajectory),
    }
    add_gnb_markers(config, bounds, report)

    output_paths["blend_file"].parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output_paths["blend_file"]))

    metadata = {
        "scene_type": "external_loop_3000m",
        "source_blend": str(source_blend),
        "prepared_blend": str(output_paths["blend_file"]),
        "scale_report": report,
        "xy_bounds_m": list(bounds),
        "track_length_estimate_m": final_length,
        "trajectory_method": trajectory_method,
        "rx_trajectory_samples": trajectory,
        "all_gnb_positions_m": report["created_gnb_positions_m"],
    }
    output_paths["scene_metadata"].write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    report_path = output_paths["scene_metadata"].with_name("scale_report.md")
    write_markdown_report(report_path, report)
    print(f"Saved prepared Blender scene to {output_paths['blend_file']}")
    print(f"Saved metadata to {output_paths['scene_metadata']}")
    print(f"Saved scale report to {report_path}")


if __name__ == "__main__":
    main()
