from __future__ import annotations

import argparse
import json
import math
import struct
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
    parser = argparse.ArgumentParser(description="Add SRTM DEM terrain to a prepared OSM railway scene.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--scene-id", required=True)
    parser.add_argument("--bbox", required=True, help="min_lat,min_lon,max_lat,max_lon")
    parser.add_argument("--hgt", required=True)
    parser.add_argument("--grid", type=int, default=180)
    return parser.parse_args(argv)


def parse_bbox(text: str) -> tuple[float, float, float, float]:
    values = [float(item.strip()) for item in text.split(",")]
    if len(values) != 4:
        raise ValueError("--bbox must contain four comma-separated numbers")
    min_lat, min_lon, max_lat, max_lon = values
    return min_lat, min_lon, max_lat, max_lon


def tile_origin(path: Path) -> tuple[int, int]:
    name = path.stem.upper()
    if len(name) < 7:
        raise ValueError(f"Cannot infer SRTM tile origin from {path.name}")
    lat_sign = 1 if name[0] == "N" else -1
    lon_sign = 1 if name[3] == "E" else -1
    return lat_sign * int(name[1:3]), lon_sign * int(name[4:7])


def hgt_sample_count(path: Path) -> int:
    count = int(math.sqrt(path.stat().st_size / 2))
    if count * count * 2 != path.stat().st_size:
        raise ValueError(f"{path} size is not a square HGT grid")
    if count not in {1201, 3601}:
        print(f"Warning: unusual HGT grid size {count}x{count}")
    return count


def hgt_value(data: bytes, count: int, row: int, col: int) -> float | None:
    row = max(0, min(count - 1, row))
    col = max(0, min(count - 1, col))
    value = struct.unpack_from(">h", data, (row * count + col) * 2)[0]
    if value == -32768:
        return None
    return float(value)


def sample_hgt(data: bytes, count: int, origin_lat: int, origin_lon: int, lat: float, lon: float) -> float:
    row_f = (origin_lat + 1.0 - lat) * (count - 1)
    col_f = (lon - origin_lon) * (count - 1)
    row0 = math.floor(row_f)
    col0 = math.floor(col_f)
    row1 = row0 + 1
    col1 = col0 + 1
    wr = row_f - row0
    wc = col_f - col0
    weighted = []
    for row, row_weight in ((row0, 1.0 - wr), (row1, wr)):
        for col, col_weight in ((col0, 1.0 - wc), (col1, wc)):
            value = hgt_value(data, count, int(row), int(col))
            if value is not None:
                weighted.append((value, row_weight * col_weight))
    if not weighted:
        return 0.0
    total_weight = sum(weight for _, weight in weighted)
    return sum(value * weight for value, weight in weighted) / max(total_weight, 1e-9)


def world_bbox_xy(obj: bpy.types.Object) -> tuple[float, float, float, float] | None:
    if not obj.bound_box:
        return None
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    xs = [corner.x for corner in corners]
    ys = [corner.y for corner in corners]
    return min(xs), min(ys), max(xs), max(ys)


def scene_bounds(metadata: dict) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for obj in bpy.data.objects:
        if obj.type not in {"MESH", "CURVE"}:
            continue
        if obj.name.startswith(("RT_", "GNB_", "Train_Static_RT_Body")):
            continue
        bbox = world_bbox_xy(obj)
        if bbox is None:
            continue
        min_x, min_y, max_x, max_y = bbox
        xs.extend([min_x, max_x])
        ys.extend([min_y, max_y])
    for point in metadata.get("rx_trajectory_samples", []):
        xs.append(float(point[0]))
        ys.append(float(point[1]))
    if not xs or not ys:
        raise ValueError("Cannot infer scene XY bounds for DEM alignment")
    pad_x = max(10.0, (max(xs) - min(xs)) * 0.03)
    pad_y = max(10.0, (max(ys) - min(ys)) * 0.03)
    return min(xs) - pad_x, min(ys) - pad_y, max(xs) + pad_x, max(ys) + pad_y


def scene_to_latlon(
    x: float,
    y: float,
    bounds: tuple[float, float, float, float],
    bbox: tuple[float, float, float, float],
) -> tuple[float, float]:
    min_x, min_y, max_x, max_y = bounds
    min_lat, min_lon, max_lat, max_lon = bbox
    x_alpha = 0.0 if max_x == min_x else (x - min_x) / (max_x - min_x)
    y_alpha = 0.0 if max_y == min_y else (y - min_y) / (max_y - min_y)
    lon = min_lon + max(0.0, min(1.0, x_alpha)) * (max_lon - min_lon)
    lat = min_lat + max(0.0, min(1.0, y_alpha)) * (max_lat - min_lat)
    return lat, lon


def make_material() -> bpy.types.Material:
    material = bpy.data.materials.get("RT_DEM_HaiVan_Laterite") or bpy.data.materials.new("RT_DEM_HaiVan_Laterite")
    material.diffuse_color = (0.37, 0.31, 0.22, 1.0)
    material["sionna_bsdf_id"] = "mat-vn_laterite"
    material["mitsuba_bsdf_id"] = "mat-vn_laterite"
    return material


def delete_flat_ground() -> None:
    for obj in list(bpy.data.objects):
        if obj.name.startswith("RT_Ground"):
            bpy.data.objects.remove(obj, do_unlink=True)


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def create_dem_mesh(
    bounds: tuple[float, float, float, float],
    bbox: tuple[float, float, float, float],
    hgt_data: bytes,
    hgt_count: int,
    origin_lat: int,
    origin_lon: int,
    z_reference: float,
    grid: int,
    material: bpy.types.Material,
) -> tuple[bpy.types.Object, dict]:
    min_x, min_y, max_x, max_y = bounds
    width = max_x - min_x
    height = max_y - min_y
    grid = max(20, min(grid, 260))
    if width >= height:
        nx = grid
        ny = max(20, int(round(grid * height / max(width, 1e-9))))
    else:
        ny = grid
        nx = max(20, int(round(grid * width / max(height, 1e-9))))
    vertices = []
    elevations = []
    for row in range(ny):
        y = min_y + height * row / max(ny - 1, 1)
        for col in range(nx):
            x = min_x + width * col / max(nx - 1, 1)
            lat, lon = scene_to_latlon(x, y, bounds, bbox)
            elev = sample_hgt(hgt_data, hgt_count, origin_lat, origin_lon, lat, lon)
            elevations.append(elev)
            vertices.append((x, y, elev - z_reference))
    faces = []
    for row in range(ny - 1):
        for col in range(nx - 1):
            idx = row * nx + col
            faces.append((idx, idx + 1, idx + nx + 1, idx + nx))
    mesh = bpy.data.meshes.new("RT_DEM_HaiVan_SRTM_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new("RT_DEM_HaiVan_SRTM", mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    obj["sionna_bsdf_id"] = "mat-vn_laterite"
    stats = {
        "grid_x": nx,
        "grid_y": ny,
        "elevation_min_m": min(elevations),
        "elevation_max_m": max(elevations),
        "elevation_mean_m": sum(elevations) / len(elevations),
    }
    return obj, stats


def curve_point_xy(point) -> tuple[float, float]:
    w = point.co.w if abs(point.co.w) > 1e-9 else 1.0
    return point.co.x / w, point.co.y / w


def adjust_rt_curves(terrain_z, offsets: dict[str, float]) -> None:
    for obj in bpy.data.objects:
        if obj.type != "CURVE":
            continue
        offset = None
        for prefix, value in offsets.items():
            if obj.name.startswith(prefix):
                offset = value
                break
        if offset is None:
            continue
        for spline in obj.data.splines:
            if spline.type == "POLY":
                for point in spline.points:
                    x, y = curve_point_xy(point)
                    point.co.z = terrain_z(x, y) + offset
            elif spline.type == "BEZIER":
                for point in spline.bezier_points:
                    z = terrain_z(point.co.x, point.co.y) + offset
                    point.co.z = z
                    point.handle_left.z = z
                    point.handle_right.z = z


def adjust_ballast(terrain_z) -> None:
    for obj in bpy.data.objects:
        if not obj.name.startswith("RT_Ballast") or obj.type != "MESH":
            continue
        for vertex in obj.data.vertices:
            world = obj.matrix_world @ vertex.co
            vertex.co.z += terrain_z(world.x, world.y) - world.z - 0.03
        obj.data.update()


def min_world_z(obj: bpy.types.Object) -> float:
    if not obj.bound_box:
        return float(obj.location.z)
    return min((obj.matrix_world @ Vector(corner)).z for corner in obj.bound_box)


def bbox_center_xy(obj: bpy.types.Object) -> tuple[float, float]:
    if not obj.bound_box:
        return float(obj.location.x), float(obj.location.y)
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    return sum(corner.x for corner in corners) / len(corners), sum(corner.y for corner in corners) / len(corners)


def ground_osm_objects(terrain_z) -> None:
    for obj in bpy.data.objects:
        if obj.type not in {"MESH", "CURVE"}:
            continue
        if obj.name.startswith(("RT_", "GNB_", "Train_Static_RT_Body")):
            continue
        x, y = bbox_center_xy(obj)
        obj.location.z += terrain_z(x, y) - min_world_z(obj)


def adjust_gnbs_and_train(metadata: dict, terrain_z, rx_height: float) -> None:
    gnb_height_by_xy: dict[tuple[int, int], float] = {}
    new_gnbs = []
    for point in metadata.get("all_gnb_positions_m", []):
        x, y, old_z = float(point[0]), float(point[1]), float(point[2])
        height_above_ground = max(5.0, old_z)
        gnb_height_by_xy[(round(x, 3), round(y, 3))] = height_above_ground
        new_gnbs.append([x, y, terrain_z(x, y) + height_above_ground])
    metadata["all_gnb_positions_m"] = new_gnbs

    for obj in bpy.data.objects:
        if obj.name.startswith("GNB_") and obj.type in {"MESH", "CURVE"}:
            x, y = bbox_center_xy(obj)
            ground_z = terrain_z(x, y)
            if "_Mast" in obj.name:
                obj.location.z = ground_z + max(1.0, obj.dimensions.z) / 2.0
            elif "_Antenna" in obj.name:
                key = min(gnb_height_by_xy, key=lambda item: math.hypot(item[0] - x, item[1] - y)) if gnb_height_by_xy else None
                height = gnb_height_by_xy[key] if key is not None else max(15.0, obj.location.z)
                obj.location.z = ground_z + height

    if "train_static_position_m" in metadata:
        x, y, old_z = [float(item) for item in metadata["train_static_position_m"]]
        metadata["train_static_position_m"] = [x, y, terrain_z(x, y) + max(1.0, old_z)]
    train_obj = bpy.data.objects.get("Train_Static_RT_Body")
    if train_obj is not None:
        x, y = bbox_center_xy(train_obj)
        train_obj.location.z = terrain_z(x, y) + 2.15

    metadata["rx_trajectory_samples"] = [
        [float(point[0]), float(point[1]), terrain_z(float(point[0]), float(point[1])) + rx_height]
        for point in metadata.get("rx_trajectory_samples", [])
    ]


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    output_paths = resolve_output_paths(config)
    metadata_path = output_paths["scene_metadata"]
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    bbox = parse_bbox(args.bbox)
    hgt_path = Path(args.hgt).resolve()
    hgt_count = hgt_sample_count(hgt_path)
    hgt_data = hgt_path.read_bytes()
    origin_lat, origin_lon = tile_origin(hgt_path)
    bounds = scene_bounds(metadata)

    rail_elevations = []
    for point in metadata.get("rx_trajectory_samples", []):
        lat, lon = scene_to_latlon(float(point[0]), float(point[1]), bounds, bbox)
        rail_elevations.append(sample_hgt(hgt_data, hgt_count, origin_lat, origin_lon, lat, lon))
    z_reference = median(rail_elevations)

    def terrain_z(x: float, y: float) -> float:
        lat, lon = scene_to_latlon(x, y, bounds, bbox)
        return sample_hgt(hgt_data, hgt_count, origin_lat, origin_lon, lat, lon) - z_reference

    delete_flat_ground()
    dem_obj, stats = create_dem_mesh(bounds, bbox, hgt_data, hgt_count, origin_lat, origin_lon, z_reference, args.grid, make_material())
    adjust_rt_curves(terrain_z, {"RT_Rail": 0.16, "RT_Trajectory_Centerline": 0.32})
    adjust_ballast(terrain_z)
    ground_osm_objects(terrain_z)
    adjust_gnbs_and_train(metadata, terrain_z, float(config.get("train", {}).get("receiver_height_m", 4.2)))

    metadata["dem"] = {
        "enabled": True,
        "source": "SRTM HGT via public elevation-tiles-prod/skadi mirror",
        "hgt_file": str(hgt_path),
        "tile": hgt_path.stem,
        "bbox_latlon": list(bbox),
        "scene_xy_bounds_m": list(bounds),
        "vertical_reference": "scene_z_m = SRTM_elevation_m - median_SRTM_elevation_on_rail_samples",
        "rail_reference_elevation_m": z_reference,
        "object_name": dem_obj.name,
        **stats,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    output_paths["blend_file"].with_suffix(".report.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    bpy.ops.wm.save_as_mainfile(filepath=str(output_paths["blend_file"]))
    print(
        f"Added DEM to {args.scene_id}: tile={hgt_path.stem}, grid={stats['grid_x']}x{stats['grid_y']}, "
        f"elev={stats['elevation_min_m']:.1f}..{stats['elevation_max_m']:.1f} m, rail_ref={z_reference:.1f} m"
    )


if __name__ == "__main__":
    main()
