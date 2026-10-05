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


DEFAULT_MAIN_RAIL_WAY_ID = 10575596
DEFAULT_SEGMENT_START_M = 500.0
DEFAULT_SEGMENT_LENGTH_M = 3000.0
DEFAULT_CORRIDOR_HALF_WIDTH_M = 260.0
TRACK_GAUGE_M = 1.435


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser(description="Generate an OSM-based Hanoi-Haiphong railway RT scene.")
    parser.add_argument("--osm-json", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--rail-way-id", type=int, default=DEFAULT_MAIN_RAIL_WAY_ID)
    parser.add_argument("--segment-start-m", type=float, default=DEFAULT_SEGMENT_START_M)
    parser.add_argument("--segment-length-m", type=float, default=DEFAULT_SEGMENT_LENGTH_M)
    parser.add_argument("--corridor-half-width-m", type=float, default=DEFAULT_CORRIDOR_HALF_WIDTH_M)
    return parser.parse_args(argv)


def mat(name: str, color, bsdf: str) -> bpy.types.Material:
    material = bpy.data.materials.new(name)
    material.diffuse_color = color
    material["sionna_bsdf_id"] = bsdf
    return material


def tag(obj: bpy.types.Object, material: bpy.types.Material, bsdf: str) -> bpy.types.Object:
    obj.data.materials.clear()
    obj.data.materials.append(material)
    obj["sionna_bsdf_id"] = bsdf
    return obj


def local_xy(lat: float, lon: float, lat0: float, lon0: float) -> Vector:
    x = (lon - lon0) * 111_320.0 * math.cos(math.radians(lat0))
    y = (lat - lat0) * 110_574.0
    return Vector((x, y, 0.0))


def polyline_lengths(points: list[Vector]) -> list[float]:
    values = [0.0]
    total = 0.0
    for a, b in zip(points, points[1:]):
        total += (b - a).length
        values.append(total)
    return values


def point_at_s(points: list[Vector], cumulative: list[float], s: float) -> tuple[Vector, Vector]:
    s = max(0.0, min(s, cumulative[-1]))
    for idx in range(len(cumulative) - 1):
        if cumulative[idx] <= s <= cumulative[idx + 1]:
            a, b = points[idx], points[idx + 1]
            length = max(cumulative[idx + 1] - cumulative[idx], 1e-9)
            p = a.lerp(b, (s - cumulative[idx]) / length)
            return p, (b - a).normalized()
    return points[-1].copy(), (points[-1] - points[-2]).normalized()


def resample(points: list[Vector], cumulative: list[float], start_m: float, end_m: float, spacing_m: float) -> list[Vector]:
    samples = []
    s = start_m
    while s < end_m:
        samples.append(point_at_s(points, cumulative, s)[0])
        s += spacing_m
    samples.append(point_at_s(points, cumulative, end_m)[0])
    origin = samples[0].copy()
    return [p - origin for p in samples]


def distance_to_polyline(point: Vector, polyline: list[Vector]) -> float:
    best = float("inf")
    for a, b in zip(polyline, polyline[1:]):
        ab = b - a
        length2 = max(ab.dot(ab), 1e-9)
        t = max(0.0, min(1.0, (point - a).dot(ab) / length2))
        projection = a + ab * t
        best = min(best, (point - projection).length)
    return best


def add_cube(name: str, loc, dims, yaw: float, material, bsdf: str) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=loc, rotation=(0.0, 0.0, yaw))
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dims
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return tag(obj, material, bsdf)


def add_box_between(name: str, a: Vector, b: Vector, lateral: float, z_center: float, width: float, height: float, material, bsdf: str) -> bpy.types.Object | None:
    d = b - a
    length = math.hypot(d.x, d.y)
    if length < 0.5:
        return None
    yaw = math.atan2(d.y, d.x)
    normal = Vector((-math.sin(yaw), math.cos(yaw), 0.0))
    mid = (a + b) * 0.5 + normal * lateral
    return add_cube(name, (mid.x, mid.y, z_center), (length, width, height), yaw, material, bsdf)


def add_centerline(points: list[Vector]) -> None:
    mesh = bpy.data.meshes.new("RT_Trajectory_Centerline_Mesh")
    verts = [(p.x, p.y, 0.0) for p in points]
    edges = [(idx, idx + 1) for idx in range(len(points) - 1)]
    mesh.from_pydata(verts, edges, [])
    mesh.update()
    obj = bpy.data.objects.new("RT_Trajectory_Centerline", mesh)
    bpy.context.scene.collection.objects.link(obj)


def polygon_center(points: list[Vector]) -> Vector:
    if not points:
        return Vector((0.0, 0.0, 0.0))
    return sum(points, Vector((0.0, 0.0, 0.0))) / len(points)


def polygon_bbox(points: list[Vector]) -> tuple[float, float, float, float]:
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    return min(xs), max(xs), min(ys), max(ys)


def add_polygon_box(name: str, points: list[Vector], height: float, material, bsdf: str) -> bpy.types.Object | None:
    if len(points) < 3:
        return None
    min_x, max_x, min_y, max_y = polygon_bbox(points)
    dx, dy = max_x - min_x, max_y - min_y
    if dx < 2.0 or dy < 2.0:
        return None
    center = ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0, height / 2.0)
    return add_cube(name, center, (dx, dy, height), 0.0, material, bsdf)


def add_gnb(name: str, position: Vector, materials: dict) -> None:
    bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.25, depth=25.0, location=(position.x, position.y, 12.5))
    mast = bpy.context.object
    mast.name = f"{name}_mast"
    tag(mast, materials["metal"], "mat-vn_metal")
    add_cube(f"{name}_antenna", (position.x, position.y, 25.0), (0.8, 0.25, 1.2), 0.0, materials["metal"], "mat-vn_metal")


def main() -> None:
    args = parse_args()
    data = json.loads(Path(args.osm_json).read_text(encoding="utf-8"))
    rail_way = next(e for e in data["elements"] if e.get("type") == "way" and e.get("id") == args.rail_way_id)
    rail_geo = rail_way["geometry"]
    lat0 = sum(p["lat"] for p in rail_geo) / len(rail_geo)
    lon0 = sum(p["lon"] for p in rail_geo) / len(rail_geo)
    rail_points_full = [local_xy(p["lat"], p["lon"], lat0, lon0) for p in rail_geo]
    cumulative = polyline_lengths(rail_points_full)
    start = min(args.segment_start_m, max(0.0, cumulative[-1] - args.segment_length_m))
    end = min(start + args.segment_length_m, cumulative[-1])
    centerline = resample(rail_points_full, cumulative, start, end, 25.0)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = 1.0

    materials = {
        "metal": mat("OSM_Metal", (0.55, 0.55, 0.58, 1.0), "mat-vn_metal"),
        "concrete": mat("OSM_Concrete", (0.48, 0.48, 0.45, 1.0), "mat-vn_concrete"),
        "asphalt": mat("OSM_Asphalt", (0.12, 0.12, 0.12, 1.0), "mat-vn_concrete_rough"),
        "water": mat("OSM_Water_Wet", (0.05, 0.15, 0.20, 1.0), "mat-vn_wet_ground"),
        "vegetation": mat("OSM_Vegetation", (0.05, 0.32, 0.11, 1.0), "mat-vn_vegetation"),
        "ground": mat("OSM_Ground", (0.32, 0.28, 0.18, 1.0), "mat-vn_laterite"),
        "ballast": mat("OSM_Ballast", (0.25, 0.25, 0.24, 1.0), "mat-vn_concrete"),
    }

    add_centerline(centerline)
    xs = [p.x for p in centerline]
    ys = [p.y for p in centerline]
    add_cube(
        "OSM_Ground_Base",
        ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0, -0.08),
        ((max(xs) - min(xs)) + 2 * args.corridor_half_width_m, (max(ys) - min(ys)) + 2 * args.corridor_half_width_m, 0.16),
        0.0,
        materials["ground"],
        "mat-vn_laterite",
    )

    for idx, (a, b) in enumerate(zip(centerline, centerline[1:])):
        add_box_between(f"Rail_Ballast_{idx:03d}", a, b, 0.0, 0.12, 5.0, 0.24, materials["ballast"], "mat-vn_concrete")
        add_box_between(f"Rail_L_{idx:03d}", a, b, TRACK_GAUGE_M / 2.0, 0.34, 0.08, 0.16, materials["metal"], "mat-vn_metal")
        add_box_between(f"Rail_R_{idx:03d}", a, b, -TRACK_GAUGE_M / 2.0, 0.34, 0.08, 0.16, materials["metal"], "mat-vn_metal")
        if idx % 2 == 0:
            add_box_between(f"Sleeper_{idx:03d}", a, b, 0.0, 0.22, 2.6, 0.18, materials["concrete"], "mat-vn_concrete")

    counts = {"buildings": 0, "roads": 0, "water": 0}
    origin = point_at_s(rail_points_full, cumulative, start)[0]
    for element in data["elements"]:
        if element.get("type") != "way" or "geometry" not in element:
            continue
        tags = element.get("tags", {})
        points = [local_xy(p["lat"], p["lon"], lat0, lon0) - origin for p in element["geometry"]]
        if not points:
            continue
        if distance_to_polyline(polygon_center(points), centerline) > args.corridor_half_width_m:
            continue
        if "building" in tags:
            levels = int(float(tags.get("building:levels", "2") or 2)) if str(tags.get("building:levels", "2")).replace(".", "", 1).isdigit() else 2
            height = float(tags.get("height", 3.5 * levels) or 3.5 * levels)
            if add_polygon_box(f"OSM_Building_{element['id']}", points, min(max(height, 3.5), 28.0), materials["concrete"], "mat-vn_concrete"):
                counts["buildings"] += 1
        elif "highway" in tags:
            width = 9.0 if tags.get("highway") in {"primary", "secondary", "tertiary"} else 5.0
            for idx, (a, b) in enumerate(zip(points, points[1:])):
                if add_box_between(f"OSM_Road_{element['id']}_{idx:02d}", a, b, 0.0, 0.025, width, 0.05, materials["asphalt"], "mat-vn_concrete_rough"):
                    counts["roads"] += 1
        elif tags.get("natural") == "water" or "waterway" in tags:
            if len(points) >= 3:
                if add_polygon_box(f"OSM_Water_{element['id']}", points, 0.05, materials["water"], "mat-vn_wet_ground"):
                    counts["water"] += 1
            else:
                for idx, (a, b) in enumerate(zip(points, points[1:])):
                    if add_box_between(f"OSM_Waterway_{element['id']}_{idx:02d}", a, b, 0.0, 0.01, 8.0, 0.03, materials["water"], "mat-vn_wet_ground"):
                        counts["water"] += 1

    segment_length = end - start
    gnb_specs = [
        ("GNB_A", segment_length * 0.12, -45.0),
        ("GNB_B", segment_length * 0.38, 55.0),
        ("GNB_C", segment_length * 0.65, -55.0),
        ("GNB_D", segment_length * 0.90, 60.0),
    ]
    gnb_positions = []
    gnb_report = []
    line_cum = polyline_lengths(centerline)
    for name, s_m, lateral in gnb_specs:
        p, t = point_at_s(centerline, line_cum, s_m)
        normal = Vector((-t.y, t.x, 0.0))
        pos = p + normal * lateral
        add_gnb(name, pos, materials)
        gnb_positions.append([round(pos.x, 3), round(pos.y, 3), 25.0])
        gnb_report.append({"name": name, "s_m": s_m, "lateral_offset_m": lateral, "position_m": gnb_positions[-1]})

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out))

    report = {
        "source_osm_json": str(Path(args.osm_json).resolve()),
        "source_rail_way_id": args.rail_way_id,
        "source_rail_name": rail_way.get("tags", {}).get("name"),
        "selected_segment_start_m": start,
        "selected_segment_length_m": end - start,
        "corridor_half_width_m": args.corridor_half_width_m,
        "lat0": lat0,
        "lon0": lon0,
        "trajectory_samples_authored": len(centerline),
        "object_counts": counts,
        "base_stations": gnb_report,
        "selection_rationale": "Representative rail corridor segment selected from OSM with enough length for moving-receiver ray tracing and enough nearby buildings/roads/water to create realistic multipath.",
    }
    Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    Path(args.report).with_suffix(".md").write_text(
        "\n".join(
            [
                "# OSM Hanoi-Haiphong Railway RT Scene",
                "",
                f"- Source OSM rail way: `{args.rail_way_id}`",
                f"- Selected segment length: {end - start:.1f} m",
                f"- Corridor half-width: {args.corridor_half_width_m:.1f} m",
                f"- Buildings imported: {counts['buildings']}",
                f"- Road segments imported: {counts['roads']}",
                f"- Water objects imported: {counts['water']}",
                "- GNB placement: four trackside macro/small-cell sites, alternating sides at 45-60 m lateral offset and 25 m height.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
