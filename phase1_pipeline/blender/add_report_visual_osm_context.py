from __future__ import annotations

import argparse
import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phase1_pipeline.common import load_config, resolve_output_paths


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--osm", required=True)
    parser.add_argument("--bbox", required=True, help="min_lat,min_lon,max_lat,max_lon")
    return parser.parse_args(argv)


def material(name: str, color: tuple[float, float, float, float], bsdf_id: str) -> bpy.types.Material:
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = color
    mat["sionna_bsdf_id"] = bsdf_id
    mat["mitsuba_bsdf_id"] = bsdf_id
    return mat


def parse_bbox(text: str) -> tuple[float, float, float, float]:
    vals = [float(item.strip()) for item in text.split(",")]
    if len(vals) != 4:
        raise ValueError("--bbox must contain min_lat,min_lon,max_lat,max_lon")
    return vals[0], vals[1], vals[2], vals[3]


def scene_bounds(metadata: dict) -> tuple[float, float, float, float]:
    xs = [float(item[0]) for item in metadata["rx_trajectory_samples"]]
    ys = [float(item[1]) for item in metadata["rx_trajectory_samples"]]
    for obj in bpy.data.objects:
        if obj.type not in {"MESH", "CURVE"} or not obj.bound_box:
            continue
        for corner in obj.bound_box:
            world = obj.matrix_world @ bpy.mathutils.Vector(corner) if False else None
        corners = [obj.matrix_world @ __import__("mathutils").Vector(corner) for corner in obj.bound_box]
        xs.extend([corner.x for corner in corners])
        ys.extend([corner.y for corner in corners])
    pad_x = max(100.0, (max(xs) - min(xs)) * 0.08)
    pad_y = max(100.0, (max(ys) - min(ys)) * 0.08)
    return min(xs) - pad_x, max(xs) + pad_x, min(ys) - pad_y, max(ys) + pad_y


def latlon_to_xy(lat: float, lon: float, bbox: tuple[float, float, float, float], bounds: tuple[float, float, float, float]) -> tuple[float, float]:
    min_lat, min_lon, max_lat, max_lon = bbox
    min_x, max_x, min_y, max_y = bounds
    u = (lon - min_lon) / max(max_lon - min_lon, 1e-9)
    v = (lat - min_lat) / max(max_lat - min_lat, 1e-9)
    x = min_x + u * (max_x - min_x)
    y = min_y + v * (max_y - min_y)
    return x, y


def load_osm(path: Path):
    root = ET.parse(path).getroot()
    nodes = {node.attrib["id"]: (float(node.attrib["lat"]), float(node.attrib["lon"])) for node in root.findall("node")}
    ways = []
    for way in root.findall("way"):
        tags = {tag.attrib.get("k", ""): tag.attrib.get("v", "") for tag in way.findall("tag")}
        refs = [nd.attrib["ref"] for nd in way.findall("nd") if nd.attrib["ref"] in nodes]
        ways.append((way.attrib.get("id", "way"), tags, [nodes[ref] for ref in refs]))
    return ways


def add_flat_polygon(name: str, points: list[tuple[float, float]], z: float, mat: bpy.types.Material, bsdf_id: str) -> bool:
    if len(points) < 3:
        return False
    if points[0] == points[-1]:
        points = points[:-1]
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    verts = [(x, y, z) for x, y in points]
    faces = [tuple(range(len(verts)))]
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(mat)
    obj["sionna_bsdf_id"] = bsdf_id
    obj["mitsuba_bsdf_id"] = bsdf_id
    return True


def add_polyline_strip(name: str, points: list[tuple[float, float]], width: float, z: float, mat: bpy.types.Material, bsdf_id: str) -> bool:
    if len(points) < 2:
        return False
    verts = []
    faces = []
    for idx, (x, y) in enumerate(points):
        if idx == 0:
            dx, dy = points[1][0] - x, points[1][1] - y
        else:
            dx, dy = x - points[idx - 1][0], y - points[idx - 1][1]
        length = max(math.hypot(dx, dy), 1e-9)
        nx, ny = -dy / length * width / 2.0, dx / length * width / 2.0
        verts.append((x + nx, y + ny, z))
        verts.append((x - nx, y - ny, z))
    for idx in range(len(points) - 1):
        faces.append((idx * 2, idx * 2 + 1, idx * 2 + 3, idx * 2 + 2))
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(mat)
    obj["sionna_bsdf_id"] = bsdf_id
    obj["mitsuba_bsdf_id"] = bsdf_id
    return True


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    out = resolve_output_paths(config)
    metadata = json.loads(out["scene_metadata"].read_text(encoding="utf-8"))
    bbox = parse_bbox(args.bbox)
    bounds = scene_bounds(metadata)
    water_mat = material("Report_Water_Blue", (0.02, 0.32, 0.95, 1.0), "mat-vn_wet_ground")
    vegetation_mat = material("Report_Landuse_Green", (0.12, 0.42, 0.16, 1.0), "mat-vn_vegetation")
    road_mat = material("Report_Road_Dark", (0.20, 0.20, 0.20, 1.0), "mat-vn_concrete_rough")

    counts = {"water_polygon": 0, "waterway": 0, "landuse": 0, "road": 0}
    for way_id, tags, coords in load_osm(Path(args.osm)):
        if len(coords) < 2:
            continue
        pts = [latlon_to_xy(lat, lon, bbox, bounds) for lat, lon in coords]
        is_closed = len(pts) >= 4 and pts[0] == pts[-1]
        if tags.get("natural") == "water" or "water" in tags:
            if is_closed and add_flat_polygon(f"Report_OSM_Water_{way_id}", pts, 0.04, water_mat, "mat-vn_wet_ground"):
                counts["water_polygon"] += 1
            elif add_polyline_strip(f"Report_OSM_Waterway_{way_id}", pts, 18.0, 0.05, water_mat, "mat-vn_wet_ground"):
                counts["waterway"] += 1
        elif tags.get("waterway"):
            if add_polyline_strip(f"Report_OSM_Waterway_{way_id}", pts, 14.0, 0.05, water_mat, "mat-vn_wet_ground"):
                counts["waterway"] += 1
        elif tags.get("landuse") in {"forest", "grass", "meadow", "farmland", "industrial", "residential"} and is_closed:
            if add_flat_polygon(f"Report_OSM_Landuse_{way_id}", pts, 0.02, vegetation_mat, "mat-vn_vegetation"):
                counts["landuse"] += 1
        elif tags.get("highway") and add_polyline_strip(f"Report_OSM_Road_{way_id}", pts, 7.0, 0.03, road_mat, "mat-vn_concrete_rough"):
            counts["road"] += 1

    metadata["report_visual_osm_context"] = {"osm": str(Path(args.osm).resolve()), "bounds_xy": bounds, "counts": counts}
    out["scene_metadata"].write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    bpy.ops.wm.save_as_mainfile(filepath=str(out["blend_file"]))
    print(json.dumps(metadata["report_visual_osm_context"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
