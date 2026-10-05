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


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1 :] if "--" in argv else argv[1:]
    parser = argparse.ArgumentParser(description="Generate a corrected concise Vietnam railway RT loop scene.")
    parser.add_argument("--out", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--config", required=True)
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


def add_cube(name: str, loc, dims, yaw: float, material, bsdf: str) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=loc, rotation=(0.0, 0.0, yaw))
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dims
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return tag(obj, material, bsdf)


def add_box_between(name: str, a: Vector, b: Vector, lateral: float, z_center: float, width: float, height: float, material, bsdf: str) -> bpy.types.Object:
    d = b - a
    length = max(math.hypot(d.x, d.y), 0.1)
    yaw = math.atan2(d.y, d.x)
    normal = Vector((-math.sin(yaw), math.cos(yaw), 0.0))
    mid = (a + b) * 0.5 + normal * lateral
    return add_cube(name, (mid.x, mid.y, z_center), (length, width, height), yaw, material, bsdf)


def make_rounded_rect(width: float = 1200.0, height: float = 500.0, radius: float = 100.0, step_m: float = 20.0) -> list[Vector]:
    # Clockwise closed loop. Perimeter = 2*(width-2r + height-2r) + 2*pi*r = 3228.3 m.
    pts: list[Vector] = []
    hw, hh, r = width / 2.0, height / 2.0, radius

    def append_line(a: Vector, b: Vector) -> None:
        dist = (b - a).length
        n = max(1, int(math.ceil(dist / step_m)))
        for i in range(n):
            if pts and i == 0:
                continue
            pts.append(a.lerp(b, i / n))

    def append_arc(center: Vector, start_deg: float, end_deg: float) -> None:
        arc_len = abs(math.radians(end_deg - start_deg)) * r
        n = max(4, int(math.ceil(arc_len / step_m)))
        for i in range(n + 1):
            if pts and i == 0:
                continue
            angle = math.radians(start_deg + (end_deg - start_deg) * i / n)
            pts.append(Vector((center.x + math.cos(angle) * r, center.y + math.sin(angle) * r, 0.0)))

    append_line(Vector((-hw + r, -hh, 0)), Vector((hw - r, -hh, 0)))
    append_arc(Vector((hw - r, -hh + r, 0)), -90, 0)
    append_line(Vector((hw, -hh + r, 0)), Vector((hw, hh - r, 0)))
    append_arc(Vector((hw - r, hh - r, 0)), 0, 90)
    append_line(Vector((hw - r, hh, 0)), Vector((-hw + r, hh, 0)))
    append_arc(Vector((-hw + r, hh - r, 0)), 90, 180)
    append_line(Vector((-hw, hh - r, 0)), Vector((-hw, -hh + r, 0)))
    append_arc(Vector((-hw + r, -hh + r, 0)), 180, 270)
    pts.append(pts[0].copy())
    return pts


def cumulative_lengths(points: list[Vector]) -> list[float]:
    values = [0.0]
    total = 0.0
    for a, b in zip(points, points[1:]):
        total += (b - a).length
        values.append(total)
    return values


def point_at_s(points: list[Vector], cumulative: list[float], s: float) -> tuple[Vector, Vector]:
    total = cumulative[-1]
    s = s % total
    for i in range(len(cumulative) - 1):
        if cumulative[i] <= s <= cumulative[i + 1]:
            a, b = points[i], points[i + 1]
            seg_len = max(cumulative[i + 1] - cumulative[i], 1e-9)
            p = a.lerp(b, (s - cumulative[i]) / seg_len)
            t = (b - a).normalized()
            return p, t
    a, b = points[-2], points[-1]
    return b.copy(), (b - a).normalized()


def path_slice(points: list[Vector], cumulative: list[float], s0: float, s1: float, step: float = 20.0) -> list[Vector]:
    values = []
    s = s0
    while s < s1:
        values.append(point_at_s(points, cumulative, s)[0])
        s += step
    values.append(point_at_s(points, cumulative, s1)[0])
    return values


def add_cylinder(name: str, loc, radius: float, depth: float, material, bsdf: str, vertices: int = 16) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=loc)
    obj = bpy.context.object
    obj.name = name
    return tag(obj, material, bsdf)


def add_tree(name: str, p: Vector, material_trunk, material_leaf) -> None:
    add_cylinder(f"{name}_trunk", (p.x, p.y, 4.0), 0.18, 8.0, material_trunk, "mat-vn_concrete", vertices=10)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=6, radius=2.4, location=(p.x, p.y, 9.0))
    crown = bpy.context.object
    crown.name = f"{name}_crown"
    tag(crown, material_leaf, "mat-vn_vegetation")


def add_centerline_object(points: list[Vector]) -> None:
    mesh = bpy.data.meshes.new("RT_Trajectory_Centerline_Mesh")
    verts = [(p.x, p.y, 0.0) for p in points]
    edges = [(i, i + 1) for i in range(len(points) - 1)]
    mesh.from_pydata(verts, edges, [])
    mesh.update()
    obj = bpy.data.objects.new("RT_Trajectory_Centerline", mesh)
    bpy.context.scene.collection.objects.link(obj)


def add_railway(points: list[Vector], materials: dict) -> None:
    rail_objs = []
    sleeper_objs = []
    ballast_objs = []
    for idx, (a, b) in enumerate(zip(points, points[1:])):
        if (b - a).length < 0.5:
            continue
        ballast_objs.append(add_box_between(f"Track_Ballast_{idx:03d}", a, b, 0.0, 0.12, 6.0, 0.24, materials["ballast"], "mat-vn_concrete"))
        rail_objs.append(add_box_between(f"Rail_L_{idx:03d}", a, b, 0.7175, 0.34, 0.08, 0.16, materials["metal"], "mat-vn_metal"))
        rail_objs.append(add_box_between(f"Rail_R_{idx:03d}", a, b, -0.7175, 0.34, 0.08, 0.16, materials["metal"], "mat-vn_metal"))
        if idx % 2 == 0:
            sleeper_objs.append(add_box_between(f"Sleeper_{idx:03d}", a, b, 0.0, 0.22, 2.8, 0.18, materials["concrete"], "mat-vn_concrete"))
    bpy.ops.object.select_all(action="DESELECT")
    for obj in rail_objs:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = rail_objs[0]
    bpy.ops.object.join()
    bpy.context.object.name = "Railway"
    bpy.context.object["sionna_bsdf_id"] = "mat-vn_metal"
    bpy.ops.object.select_all(action="DESELECT")
    for obj in sleeper_objs:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = sleeper_objs[0]
    bpy.ops.object.join()
    bpy.context.object.name = "Track_Sleepers"
    bpy.context.object["sionna_bsdf_id"] = "mat-vn_concrete"
    bpy.ops.object.select_all(action="DESELECT")
    for obj in ballast_objs:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = ballast_objs[0]
    bpy.ops.object.join()
    bpy.context.object.name = "Track_Ballast"
    bpy.context.object["sionna_bsdf_id"] = "mat-vn_concrete"


def add_tunnel(points: list[Vector], cumulative: list[float], materials: dict) -> dict:
    tunnel_pts = path_slice(points, cumulative, 1500.0, 2000.0, 20.0)
    for idx, (a, b) in enumerate(zip(tunnel_pts, tunnel_pts[1:])):
        add_box_between(f"Tunnel_Floor_{idx:03d}", a, b, 0.0, -0.12, 12.0, 0.24, materials["concrete"], "mat-vn_concrete")
        add_box_between(f"Tunnel_Ceiling_{idx:03d}", a, b, 0.0, 8.0, 12.0, 0.35, materials["concrete"], "mat-vn_concrete")
        add_box_between(f"Tunnel_Wall_L_{idx:03d}", a, b, 6.0, 4.0, 0.35, 8.0, materials["concrete"], "mat-vn_concrete")
        add_box_between(f"Tunnel_Wall_R_{idx:03d}", a, b, -6.0, 4.0, 0.35, 8.0, materials["concrete"], "mat-vn_concrete")
        add_box_between(f"Mountain_Overburden_{idx:03d}", a, b, 0.0, 24.0, 58.0, 32.0, materials["granite"], "mat-vn_granite")
        add_box_between(f"Mountain_RockFace_L_{idx:03d}", a, b, 28.0, 20.0, 35.0, 40.0, materials["granite"], "mat-vn_granite")
        add_box_between(f"Mountain_RockFace_R_{idx:03d}", a, b, -28.0, 20.0, 35.0, 40.0, materials["granite"], "mat-vn_granite")
    entry, entry_t = point_at_s(points, cumulative, 1500.0)
    exitp, exit_t = point_at_s(points, cumulative, 2000.0)
    for name, p, t in (("Tunnel_Portal_Entry", entry, entry_t), ("Tunnel_Portal_Exit", exitp, exit_t)):
        yaw = math.atan2(t.y, t.x)
        add_cube(name, (p.x, p.y, 4.0), (1.5, 14.0, 8.5), yaw, materials["granite"], "mat-vn_granite")
    return {"width_m": 12.0, "height_m": 8.0, "start_s_m": 1500.0, "end_s_m": 2000.0}


def add_environment(points: list[Vector], cumulative: list[float], materials: dict) -> None:
    # Base terrain and water-rich fields.
    add_cube("Ground_Laterite_Base", (0, 0, -0.08), (1500, 800, 0.16), 0.0, materials["laterite"], "mat-vn_laterite")
    for s in (150, 375, 600):
        p, t = point_at_s(points, cumulative, s)
        yaw = math.atan2(t.y, t.x)
        add_cube(f"ZoneA_Wet_Rice_Field_L_{s:.0f}", (p.x, p.y + 55, -0.02), (220, 70, 0.04), yaw, materials["wet"], "mat-vn_wet_ground")
        add_cube(f"ZoneA_Wet_Rice_Field_R_{s:.0f}", (p.x, p.y - 55, -0.02), (220, 70, 0.04), yaw, materials["wet"], "mat-vn_wet_ground")
    for s in range(50, 750, 100):
        p, t = point_at_s(points, cumulative, float(s))
        normal = Vector((-t.y, t.x, 0.0))
        add_tree(f"ZoneA_Coconut_L_{s}", p + normal * 25.0, materials["concrete"], materials["vegetation"])
        add_tree(f"ZoneA_Coconut_R_{s}", p - normal * 25.0, materials["concrete"], materials["vegetation"])
        add_cylinder(f"ZoneA_PowerPole_{s}", (p.x + normal.x * 38.0, p.y + normal.y * 38.0, 4.5), 0.09, 9.0, materials["concrete"], "mat-vn_concrete", vertices=10)

    # Zone B village: metal roofs and vegetation close enough to affect multipath.
    house_id = 0
    for s in (850, 980, 1110, 1240, 1370):
        p, t = point_at_s(points, cumulative, float(s))
        yaw = math.atan2(t.y, t.x)
        normal = Vector((-t.y, t.x, 0.0))
        for side in (-1, 1):
            base = p + normal * side * 48.0
            house_id += 1
            add_cube(f"ZoneB_House_Wall_{house_id}", (base.x, base.y, 2.0), (8.0, 10.0, 4.0), yaw, materials["brick"], "mat-vn_concrete")
            add_cube(f"ZoneB_Metal_Roof_{house_id}", (base.x, base.y, 4.9), (9.0, 11.0, 0.25), yaw, materials["metal"], "mat-vn_metal")
        canal = p - normal * 82.0
        add_cube(f"ZoneB_Irrigation_Canal_{s}", (canal.x, canal.y, 0.0), (8.0, 95.0, 0.05), yaw + math.pi / 2.0, materials["wet"], "mat-vn_wet_ground")
    for s in range(900, 1450, 90):
        p, t = point_at_s(points, cumulative, float(s))
        normal = Vector((-t.y, t.x, 0.0))
        add_tree(f"ZoneB_Orchard_{s}", p + normal * 75.0, materials["concrete"], materials["vegetation"])
        add_cylinder(f"ZoneB_Bamboo_{s}", (p.x - normal.x * 28.0, p.y - normal.y * 28.0, 6.0), 2.2, 12.0, materials["vegetation"], "mat-vn_vegetation", vertices=14)

    # Zone C forest and scree near tunnel portals.
    for s in range(1450, 2050, 75):
        p, t = point_at_s(points, cumulative, float(s))
        normal = Vector((-t.y, t.x, 0.0))
        add_tree(f"ZoneC_Forest_L_{s}", p + normal * 62.0, materials["concrete"], materials["vegetation"])
        add_tree(f"ZoneC_Forest_R_{s}", p - normal * 62.0, materials["concrete"], materials["vegetation"])
        add_cube(f"ZoneC_Talus_{s}", (p.x, p.y, 1.0), (18.0, 18.0, 2.0), math.atan2(t.y, t.x), materials["granite"], "mat-vn_granite")

    # Zone D valley recovery objects.
    for s in range(2050, 2950, 150):
        p, t = point_at_s(points, cumulative, float(s))
        normal = Vector((-t.y, t.x, 0.0))
        yaw = math.atan2(t.y, t.x)
        add_cube(f"ZoneD_Foothill_L_{s}", (p.x + normal.x * 75.0, p.y + normal.y * 75.0, 12.0), (120.0, 30.0, 24.0), yaw, materials["laterite"], "mat-vn_laterite")
        add_tree(f"ZoneD_SecondaryForest_{s}", p - normal * 55.0, materials["concrete"], materials["vegetation"])
    p, t = point_at_s(points, cumulative, 2500.0)
    normal = Vector((-t.y, t.x, 0.0))
    yaw = math.atan2(t.y, t.x)
    stream = p - normal * 85.0
    add_cube("ZoneD_Mountain_Stream", (stream.x, stream.y, 0.0), (180.0, 28.0, 0.05), yaw, materials["wet"], "mat-vn_wet_ground")
    station = p + normal * 42.0
    add_cube("ZoneD_Small_Station", (station.x, station.y, 4.0), (60.0, 14.0, 8.0), yaw, materials["concrete"], "mat-vn_concrete")


def add_train(points: list[Vector], cumulative: list[float], materials: dict) -> None:
    p, t = point_at_s(points, cumulative, 2600.0)
    yaw = math.atan2(t.y, t.x)
    add_cube("Train", (p.x, p.y, 2.2), (25.0, 3.4, 4.2), yaw, materials["metal"], "mat-vn_metal")


def gnb_positions(points: list[Vector], cumulative: list[float]) -> list[dict]:
    specs = [
        ("GNB_A", "mpc_gnb_a", 375.0, 42.0),
        ("GNB_B", "mpc_gnb_b", 1125.0, 52.0),
        # Portal-side gNB for tunnel handover/coverage. Keep it outside the rock face.
        ("GNB_C", "mpc_gnb_c", 1490.0, 70.0),
        # Put GNB_D on the opposite side of the rail from the foothill blocks/station.
        ("GNB_D", "mpc_gnb_d", 2600.0, -120.0),
    ]
    stations = []
    for name, output_name, s, offset in specs:
        p, t = point_at_s(points, cumulative, s)
        normal = Vector((-t.y, t.x, 0.0))
        pos = p + normal * offset
        stations.append({"name": name, "output_name": output_name, "position_m": [round(pos.x, 3), round(pos.y, 3), 25.0]})
    return stations


def write_config(path: Path, source_blend: Path, stations: list[dict]) -> None:
    station_yaml = "\n".join(
        [
            f"  - name: {s['name']}\n"
            f"    output_name: {s['output_name']}\n"
            f"    position_m: [{s['position_m'][0]}, {s['position_m'][1]}, {s['position_m'][2]}]\n"
            f"    facing: auto\n"
            f"    height_m: 25.0\n"
            f"    mast_radius_m: 0.25\n"
            f"    antenna_size_m: [0.8, 0.25, 1.2]\n"
            f"    ray_origin_clearance_m: 0.25"
            for s in stations
        ]
    )
    text = f"""scenario:
  type: external_loop_3000m
  name: vietnam_rt_corrected_loop

external_scene:
  source_blend: {source_blend.as_posix()}
  target_min_track_length_m: 3000.0
  remove_objects_below_area_m2: 7.0
  trajectory_spacing_m: 25.0
  place_gnbs_at_scene_corners: false
  small_object_keep_keywords: [rail, track, gnb, tx, antenna, tunnel, portal, sleeper]

export:
  max_obj_file_bytes: 30000000

scene:
  length_m: 3200.0
  width_m: 900.0

base_stations:
{station_yaml}

train:
  receiver_height_m: 4.2
  lateral_offset_m: 0.0
  length_m: 25.0
  width_m: 3.4
  body_height_m: 4.2

simulation:
  frequency_hz: 30000000000.0
  train_speed_kmh: 350.0
  timestep_s: 0.001
  scene_margin_m: 0.0
  duration_s:

ray_tracing:
  max_depth: 6
  max_num_paths: 3000
  samples_per_src: 3500
  include_train_in_rt_scene: false
  enable_refraction: false
  enable_diffuse_reflection: true
  enable_diffraction: true
  enable_edge_diffraction: true
  enable_diffraction_lit_region: false
  synthetic_array: true
  min_relative_path_gain_db: 75.0
  max_paths_after_filter: 128
  skip_snapshot_visualizations: true
  skip_station_validation_plots: true

antenna:
  tx_array:
    num_rows: 8
    num_cols: 4
    vertical_spacing: 0.5
    horizontal_spacing: 0.5
    pattern: tr38901
    polarization: VH
    polarization_model: tr38901_2
  rx_array:
    num_rows: 2
    num_cols: 2
    vertical_spacing: 0.5
    horizontal_spacing: 0.5
    pattern: tr38901
    polarization: VH
    polarization_model: tr38901_2

paths:
  blend_file: output_vietnam_rt_corrected/Train_vietnam_rt_corrected_sionna.blend
  mitsuba_xml: output_vietnam_rt_corrected/scene.xml
  mesh_dir: output_vietnam_rt_corrected/meshes
  trace_csv: output_vietnam_rt_corrected/ns3_trace.csv
  trace_csv_pattern: output_vietnam_rt_corrected/{{station}}.csv
  trace_manifest: output_vietnam_rt_corrected/trace_manifest.json
  doppler_plot: output_vietnam_rt_corrected/doppler_vs_time.png
  doppler_plot_pattern: output_vietnam_rt_corrected/{{station}}_doppler_vs_time.png
  path_count_plot: output_vietnam_rt_corrected/path_count_vs_time.png
  path_count_plot_pattern: output_vietnam_rt_corrected/{{station}}_path_count_vs_time.png
  scene_metadata: output_vietnam_rt_corrected/scene_metadata.json
"""
    path.write_text(text, encoding="utf-8")


def main() -> None:
    args = parse_args()
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = 1.0

    materials = {
        "metal": mat("RT_Metal", (0.55, 0.55, 0.58, 1), "mat-vn_metal"),
        "concrete": mat("RT_Concrete", (0.45, 0.45, 0.43, 1), "mat-vn_concrete"),
        "ballast": mat("RT_Ballast", (0.25, 0.25, 0.24, 1), "mat-vn_concrete"),
        "wet": mat("RT_Wet_Ground", (0.10, 0.18, 0.20, 1), "mat-vn_wet_ground"),
        "vegetation": mat("RT_Vegetation", (0.05, 0.35, 0.12, 1), "mat-vn_vegetation"),
        "granite": mat("RT_Granite", (0.42, 0.42, 0.44, 1), "mat-vn_granite"),
        "laterite": mat("RT_Laterite", (0.46, 0.20, 0.11, 1), "mat-vn_laterite"),
        "brick": mat("RT_Brick", (0.52, 0.29, 0.20, 1), "mat-vn_concrete"),
    }
    centerline = make_rounded_rect()
    cumulative = cumulative_lengths(centerline)
    add_centerline_object(centerline)
    add_railway(centerline, materials)
    tunnel = add_tunnel(centerline, cumulative, materials)
    add_environment(centerline, cumulative, materials)
    add_train(centerline, cumulative, materials)
    stations = gnb_positions(centerline, cumulative)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out))

    write_config(Path(args.config), out.resolve(), stations)
    report = {
        "blend": str(out.resolve()),
        "config": str(Path(args.config).resolve()),
        "trajectory_length_m": cumulative[-1],
        "trajectory_samples_authored": len(centerline),
        "track": {"gauge_m": 1.435, "rail_head_width_m": 0.08, "ballast_width_m": 6.0},
        "train": {"length_m": 25.0, "width_m": 3.4, "height_m": 4.2},
        "tunnel": tunnel,
        "zones_s_m": {
            "A_viaduct_rice_field": [0, 750],
            "B_village_ground": [750, 1500],
            "C_mountain_tunnel": [1500, 2000],
            "D_valley_recovery": [2000, 3000],
        },
        "base_stations": stations,
        "scale": "No scale applied. Scene was authored directly in meters.",
        "small_object_policy": "Only scene-significant objects were authored; cleanup threshold remains 7 m2 in prepare step.",
    }
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    Path(args.report).with_suffix(".md").write_text(
        "\n".join(
            [
                "# Corrected Vietnam Railway RT Scene",
                "",
                f"- Blend: `{out.resolve()}`",
                f"- Config: `{Path(args.config).resolve()}`",
                f"- Authored trajectory length: {cumulative[-1]:.3f} m",
                "- Scale applied: none; authored in meters.",
                "- Railway gauge: 1.435 m",
                "- Ballast/corridor width: 6.0 m",
                "- Train dimensions: 25.0 x 3.4 x 4.2 m",
                "- Tunnel inner size: 12.0 x 8.0 m over s=1500..2000 m",
                "- GNB placement: one station per zone, offset 42..55 m from track centerline.",
                "",
                "## Zone Mapping",
                "",
                "- Zone A: s=0..750 m, viaduct/rice field/coconut/power poles.",
                "- Zone B: s=750..1500 m, rural houses with metal roofs, orchard, bamboo, canals.",
                "- Zone C: s=1500..2000 m, curved tunnel, granite rock faces, forest, talus.",
                "- Zone D: s=2000..3000 m, laterite foothills, stream, secondary forest, station.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
