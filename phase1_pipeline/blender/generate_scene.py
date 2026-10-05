from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phase1_pipeline.common import dump_json, load_config, resolve_output_paths
from phase1_pipeline.scenarios import (
    active_base_station,
    all_base_stations,
    is_tunnel_scenario,
    is_unified_scenario,
    unified_modules,
    unified_trajectory_samples,
)


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = argv[1:]
    parser = argparse.ArgumentParser(description="Generate the railway scene in Blender.")
    parser.add_argument(
        "--config",
        default=str(ROOT / "phase1_pipeline" / "config" / "config.yaml"),
        help="Path to the pipeline YAML configuration file.",
    )
    return parser.parse_args(argv)


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for data_block in (bpy.data.meshes, bpy.data.curves, bpy.data.materials, bpy.data.collections):
        for block in list(data_block):
            if block.users == 0:
                data_block.remove(block)


def configure_scene_units() -> None:
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.render.engine = "CYCLES"


def configure_large_scene_view(center_x: float, center_y: float, center_z: float, distance: float, clip_end: float) -> None:
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            for space in area.spaces:
                if space.type != "VIEW_3D":
                    continue
                space.clip_start = 0.1
                space.clip_end = clip_end
                region_3d = getattr(space, "region_3d", None)
                if region_3d is None:
                    continue
                region_3d.view_location = (center_x, center_y, center_z)
                region_3d.view_distance = distance
                region_3d.view_rotation = (0.82, 0.42, 0.18, 0.34)


def ensure_collection(name: str) -> bpy.types.Collection:
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(collection)
    return collection


def link_to_collection(obj: bpy.types.Object, collection: bpy.types.Collection) -> None:
    for existing in list(obj.users_collection):
        existing.objects.unlink(obj)
    collection.objects.link(obj)


def create_principled_material(name, base_color, metallic, roughness, mitsuba_bsdf):
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name=name)
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    principled.inputs["Base Color"].default_value = base_color
    principled.inputs["Metallic"].default_value = metallic
    principled.inputs["Roughness"].default_value = roughness
    material["mitsuba_bsdf"] = mitsuba_bsdf
    return material


def assign_material(obj: bpy.types.Object, material: bpy.types.Material) -> None:
    if obj.data.materials:
        obj.data.materials[0] = material
    else:
        obj.data.materials.append(material)


def add_box(name: str, size, location) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = (size[0] / 2.0, size[1] / 2.0, size[2] / 2.0)
    return obj


def add_cylinder(name: str, radius: float, depth: float, location, vertices: int = 16, rotation=(0.0, 0.0, 0.0)) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=depth, vertices=vertices, location=location, rotation=rotation)
    obj = bpy.context.active_object
    obj.name = name
    return obj


def facing_offset(facing: str, distance: float) -> tuple[float, float, float]:
    mapping = {
        "x+": (distance, 0.0, 0.0),
        "x-": (-distance, 0.0, 0.0),
        "y+": (0.0, distance, 0.0),
        "y-": (0.0, -distance, 0.0),
    }
    return mapping.get(facing, (0.0, -distance, 0.0))


def build_base_stations(config, collection, materials):
    positions = []
    for idx, gnb_cfg in enumerate(all_base_stations(config)):
        x, y, z = map(float, gnb_cfg["position_m"])
        mast_height = float(gnb_cfg["height_m"])
        mast_radius = float(gnb_cfg["mast_radius_m"])
        antenna_size = tuple(float(v) for v in gnb_cfg["antenna_size_m"])
        facing = str(gnb_cfg.get("facing", "y-"))
        label = str(gnb_cfg.get("name", f"gnb_{idx}"))

        mast = add_cylinder(f"{label}_mast", mast_radius, mast_height, (x, y, mast_height / 2.0))
        assign_material(mast, materials["metal"])
        link_to_collection(mast, collection)

        dx, dy, dz = facing_offset(facing, antenna_size[1] / 2.0)
        antenna = add_box(f"{label}_antenna", antenna_size, (x + dx, y + dy, z + dz))
        if facing == "y+":
            antenna.rotation_euler = (0.0, 0.0, 0.0)
        elif facing == "x+":
            antenna.rotation_euler = (0.0, 0.0, -math.pi / 2.0)
        elif facing == "x-":
            antenna.rotation_euler = (0.0, 0.0, math.pi / 2.0)
        else:
            antenna.rotation_euler = (0.0, 0.0, math.pi)
        assign_material(antenna, materials["metal"])
        link_to_collection(antenna, collection)
        positions.append((x, y, z))
    return positions


def build_train_unified(config, collection, materials):
    trajectory = unified_trajectory_samples(config)
    rx_x, rx_y, rx_z = trajectory[0]
    train_cfg = config["train"]
    length = float(train_cfg.get("length_m", 25.0))
    width = float(train_cfg.get("width_m", 3.4))
    body_height = float(train_cfg.get("body_height_m", 3.8))
    body_center = (rx_x - 12.5, rx_y, rx_z - 2.1)
    body = add_box("TRAIN_Body", (length, width, body_height), body_center)
    assign_material(body, materials["train_body"])
    link_to_collection(body, collection)
    return body_center


def build_train_legacy(config, collection, materials):
    train_cfg = config.get("train", {})
    length = float(train_cfg.get("length_m", 25.0))
    width = float(train_cfg.get("width_m", 3.2))
    body_height = float(train_cfg.get("body_height_m", 3.6))
    nose_length = float(train_cfg.get("nose_length_m", 4.0))
    bogie_offset = float(train_cfg.get("bogie_offset_m", 7.0))
    wheel_radius = float(train_cfg.get("wheel_radius_m", 0.42))
    wheel_width = float(train_cfg.get("wheel_width_m", 0.12))
    x = -float(config["scene"]["length_m"]) / 2.0 + length / 2.0 + 4.0
    y = float(train_cfg.get("lateral_offset_m", 0.0))
    z = wheel_radius + body_height / 2.0

    body = add_box("train_body", (length - nose_length, width, body_height), (x + nose_length / 2.0, y, z))
    assign_material(body, materials["train_body"])
    link_to_collection(body, collection)

    nose = add_box("train_nose", (nose_length, width * 0.92, body_height * 0.86), (x - (length - nose_length) / 2.0, y, z + 0.08))
    assign_material(nose, materials["train_body"])
    link_to_collection(nose, collection)

    roof = add_box("train_roof", (length * 0.74, width * 0.7, 0.28), (x + 0.8, y, z + body_height / 2.0 + 0.12))
    assign_material(roof, materials["train_window"])
    link_to_collection(roof, collection)

    for idx, bogie_x in enumerate((x - bogie_offset, x + bogie_offset)):
        bogie = add_box(f"train_bogie_{idx:02d}", (2.1, 2.4, 0.45), (bogie_x, y, wheel_radius + 0.25))
        assign_material(bogie, materials["metal"])
        link_to_collection(bogie, collection)
        for side in (-1, 1):
            for wheel_shift in (-0.7, 0.7):
                wheel = add_cylinder(
                    f"train_wheel_{idx}_{'l' if side < 0 else 'r'}_{0 if wheel_shift < 0 else 1}",
                    wheel_radius,
                    wheel_width,
                    (bogie_x + wheel_shift, y + side * 1.05, wheel_radius),
                    rotation=(math.pi / 2.0, 0.0, 0.0),
                )
                assign_material(wheel, materials["metal"])
                link_to_collection(wheel, collection)

    pantograph = add_box("train_pantograph", (1.0, 0.3, 1.0), (x + 2.5, y, z + body_height / 2.0 + 0.75))
    assign_material(pantograph, materials["metal"])
    link_to_collection(pantograph, collection)
    return (x, y, z + body_height * 0.2)


def build_track_legacy(config, collection, materials) -> None:
    scene_cfg = config["scene"]
    track_cfg = config["railway"]
    length = float(scene_cfg["length_m"])
    rail_height = float(track_cfg["rail_height_m"])
    rail_width = float(track_cfg["rail_width_m"])
    gauge = float(track_cfg["gauge_m"])
    sleeper_spacing = float(track_cfg["sleeper_spacing_m"])
    sleeper_dims = track_cfg["sleeper_dimensions_m"]

    half_gauge = gauge / 2.0
    rail_z = rail_height / 2.0
    for suffix, y in (("left", half_gauge), ("right", -half_gauge)):
        rail = add_box(f"rail_{suffix}", (length, rail_width, rail_height), (0.0, y, rail_z))
        assign_material(rail, materials["metal"])
        link_to_collection(rail, collection)

    sleeper_count = int(length / sleeper_spacing) + 1
    sleeper_width, sleeper_depth, sleeper_height = sleeper_dims
    for idx in range(sleeper_count):
        x = -length / 2.0 + idx * sleeper_spacing
        sleeper = add_box(
            f"sleeper_{idx:03d}",
            (sleeper_width, sleeper_depth, sleeper_height),
            (x, 0.0, sleeper_height / 2.0 - 0.02),
        )
        assign_material(sleeper, materials["concrete"])
        link_to_collection(sleeper, collection)


def build_ground_legacy(config, collection, materials) -> None:
    scene_cfg = config["scene"]
    length = float(scene_cfg["length_m"])
    width = float(scene_cfg["width_m"])
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0.0, 0.0, 0.0))
    ground = bpy.context.active_object
    ground.name = "ground"
    ground.scale = (length / 2.0, width / 2.0, 1.0)
    assign_material(ground, materials["ground"])
    link_to_collection(ground, collection)


def build_barriers_legacy(config, collection, materials) -> None:
    scene_cfg = config["scene"]
    barrier_cfg = config["noise_barriers"]
    length = float(scene_cfg["length_m"])
    height = float(barrier_cfg["height_m"])
    thickness = float(barrier_cfg["thickness_m"])
    offset = float(barrier_cfg["center_offset_m"])
    for suffix, y in (("north", offset), ("south", -offset)):
        barrier = add_box(f"barrier_{suffix}", (length, thickness, height), (0.0, y, height / 2.0))
        assign_material(barrier, materials["concrete"])
        link_to_collection(barrier, collection)


def build_tunnel_legacy(config, collection, materials) -> None:
    tunnel_cfg = config["tunnel"]
    tunnel_length = float(tunnel_cfg["length_m"])
    tunnel_width = float(tunnel_cfg["inner_width_m"])
    tunnel_height = float(tunnel_cfg["inner_height_m"])
    wall_thickness = float(tunnel_cfg.get("wall_thickness_m", 0.35))
    tunnel_center_x = float(tunnel_cfg.get("center_x_m", 0.0))
    floor = add_box("tunnel_floor", (tunnel_length + wall_thickness * 2.0, tunnel_width + wall_thickness * 2.0, wall_thickness), (tunnel_center_x, 0.0, -wall_thickness / 2.0))
    assign_material(floor, materials["concrete"])
    link_to_collection(floor, collection)
    for suffix, y in (("north", tunnel_width / 2.0 + wall_thickness / 2.0), ("south", -tunnel_width / 2.0 - wall_thickness / 2.0)):
        wall = add_box(f"tunnel_wall_{suffix}", (tunnel_length, wall_thickness, tunnel_height), (tunnel_center_x, y, tunnel_height / 2.0))
        assign_material(wall, materials["concrete"])
        link_to_collection(wall, collection)
    roof = add_box("tunnel_roof", (tunnel_length, tunnel_width + wall_thickness * 2.0, wall_thickness), (tunnel_center_x, 0.0, tunnel_height + wall_thickness / 2.0))
    assign_material(roof, materials["concrete"])
    link_to_collection(roof, collection)
    for suffix, x in (("west", tunnel_center_x - tunnel_length / 2.0), ("east", tunnel_center_x + tunnel_length / 2.0)):
        frame = add_box(f"portal_frame_{suffix}", (wall_thickness, tunnel_width + wall_thickness * 2.0, tunnel_height + wall_thickness), (x, 0.0, tunnel_height / 2.0))
        assign_material(frame, materials["concrete"])
        link_to_collection(frame, collection)


def build_catenary_legacy(config, collection, materials) -> None:
    scene_cfg = config["scene"]
    catenary_cfg = config["catenary"]
    length = float(scene_cfg["length_m"])
    pole_spacing = float(catenary_cfg["pole_spacing_m"])
    pole_height = float(catenary_cfg["pole_height_m"])
    pole_offset = float(catenary_cfg["pole_offset_m"])
    wire_height = float(catenary_cfg["wire_height_m"])
    pole_radius = float(catenary_cfg["pole_radius_m"])
    pole_count = int(length / pole_spacing) + 1
    for idx in range(pole_count):
        x = -length / 2.0 + idx * pole_spacing
        pole = add_cylinder(f"catenary_pole_{idx:03d}", pole_radius, pole_height, (x, pole_offset, pole_height / 2.0), vertices=12)
        assign_material(pole, materials["metal"])
        link_to_collection(pole, collection)
        arm = add_box(f"catenary_arm_{idx:03d}", (0.3, pole_offset, 0.12), (x, pole_offset / 2.0, wire_height))
        assign_material(arm, materials["metal"])
        link_to_collection(arm, collection)
    contact = add_box("contact_wire", (length, 0.02, 0.02), (0.0, 0.0, wire_height))
    assign_material(contact, materials["copper"])
    link_to_collection(contact, collection)
    messenger = add_box("messenger_wire", (length, 0.02, 0.02), (0.0, 0.0, wire_height + 0.45))
    assign_material(messenger, materials["copper"])
    link_to_collection(messenger, collection)


def build_unified_scene(config, collections, materials):
    structures = collections["Structures"]
    track = collections["Track"]
    catenary = collections["Catenary"]
    tunnel = collections["Tunnel"]

    ground = add_box("GROUND_OUTDOOR", (3000.0, 200.0, 0.6), (1500.0, 0.0, -0.3))
    assign_material(ground, materials["ground"])
    link_to_collection(ground, structures)

    # Module A
    for name, size, location, mat_key, target in (
        ("VIADUCT_A_Deck", (700.0, 12.0, 2.0), (350.0, 0.0, 11.0), "concrete", structures),
        ("TRACKBED_A", (700.0, 3.2, 0.3), (350.0, 0.0, 11.85), "concrete", track),
        ("RAIL_A_Left", (700.0, 0.07, 0.172), (350.0, -0.7175, 12.086), "metal", track),
        ("RAIL_A_Right", (700.0, 0.07, 0.172), (350.0, 0.7175, 12.086), "metal", track),
        ("PARAPET_A_Left", (700.0, 0.25, 1.2), (350.0, -5.875, 12.6), "concrete", structures),
        ("PARAPET_A_Right", (700.0, 0.25, 1.2), (350.0, 5.875, 12.6), "concrete", structures),
        ("BARRIER_A_Left", (700.0, 0.20, 3.5), (350.0, -3.6, 13.75), "concrete", structures),
        ("BARRIER_A_Right", (700.0, 0.20, 3.5), (350.0, 3.6, 13.75), "concrete", structures),
        ("WIRE_A_Catenary", (700.0, 0.02, 0.02), (350.0, -0.2, 17.5), "copper", catenary),
    ):
        obj = add_box(name, size, location)
        assign_material(obj, materials[mat_key])
        link_to_collection(obj, target)
    for idx in range(14):
        pier = add_box(f"PIER_A_{idx + 1:02d}", (3.0, 6.0, 10.0), (50.0 * (idx + 1), 0.0, 5.0))
        assign_material(pier, materials["concrete"])
        link_to_collection(pier, structures)
    for idx in range(12):
        pole = add_cylinder(f"POLE_A_{idx + 1:02d}", 0.15, 7.0, (30.0 + 60.0 * idx, -2.5, 15.5), vertices=12)
        assign_material(pole, materials["metal"])
        link_to_collection(pole, catenary)

    # Module B
    for name, size, location, mat_key, target in (
        ("TRACKBED_B", (400.0, 3.2, 0.3), (900.0, 0.0, -0.15), "concrete", track),
        ("RAIL_B_Left", (400.0, 0.07, 0.172), (900.0, -0.7175, 0.086), "metal", track),
        ("RAIL_B_Right", (400.0, 0.07, 0.172), (900.0, 0.7175, 0.086), "metal", track),
        ("BARRIER_B_Left", (400.0, 0.20, 3.5), (900.0, -3.6, 1.75), "concrete", structures),
        ("BARRIER_B_Right", (400.0, 0.20, 3.5), (900.0, 3.6, 1.75), "concrete", structures),
        ("WIRE_B_Catenary", (400.0, 0.02, 0.02), (900.0, -0.2, 5.5), "copper", catenary),
    ):
        obj = add_box(name, size, location)
        assign_material(obj, materials[mat_key])
        link_to_collection(obj, target)
    for idx in range(7):
        pole = add_cylinder(f"POLE_B_{idx + 1:02d}", 0.15, 7.0, (700.0 + 60.0 * idx, -2.5, 3.5), vertices=12)
        assign_material(pole, materials["metal"])
        link_to_collection(pole, catenary)

    # Module C
    for name, size, location, mat_key, target in (
        ("TRACKBED_C", (200.0, 3.2, 0.3), (1200.0, 0.0, -0.15), "concrete", track),
        ("RAIL_C_Left", (200.0, 0.07, 0.172), (1200.0, -0.7175, 0.086), "metal", track),
        ("RAIL_C_Right", (200.0, 0.07, 0.172), (1200.0, 0.7175, 0.086), "metal", track),
        ("BARRIER_C_Left", (100.0, 0.20, 3.5), (1150.0, -3.6, 1.75), "concrete", structures),
        ("BARRIER_C_Right", (100.0, 0.20, 3.5), (1150.0, 3.6, 1.75), "concrete", structures),
    ):
        obj = add_box(name, size, location)
        assign_material(obj, materials[mat_key])
        link_to_collection(obj, target)
    for idx, x in enumerate((1120.0, 1180.0), start=1):
        pole = add_cylinder(f"POLE_C_{idx:02d}", 0.15, 7.0, (x, -2.5, 3.5), vertices=12)
        assign_material(pole, materials["metal"])
        link_to_collection(pole, catenary)
    for side, y in (("Left", -5.25), ("Right", 5.25)):
        for step_idx, (x, height) in enumerate(((1175.0, 3.0), (1225.0, 5.0), (1275.0, 7.5)), start=1):
            wall = add_box(f"STEEPWALL_C_{side}_{step_idx}", (50.0, 0.5, height), (x, y, height / 2.0))
            assign_material(wall, materials["granite"])
            link_to_collection(wall, structures)

    # Module D
    for name, size, location, mat_key in (
        ("TUNNEL_D_Floor", (300.0, 10.0, 0.5), (1450.0, 0.0, -0.25), "concrete"),
        ("TUNNEL_D_Ceiling", (300.0, 10.0, 0.5), (1450.0, 0.0, 7.75), "concrete"),
        ("TUNNEL_D_WallLeft", (300.0, 0.5, 7.5), (1450.0, -5.25, 3.75), "concrete"),
        ("TUNNEL_D_WallRight", (300.0, 0.5, 7.5), (1450.0, 5.25, 3.75), "concrete"),
        ("RAIL_D_Left", (300.0, 0.07, 0.172), (1450.0, -0.7175, 0.086), "metal"),
        ("RAIL_D_Right", (300.0, 0.07, 0.172), (1450.0, 0.7175, 0.086), "metal"),
    ):
        obj = add_box(name, size, location)
        assign_material(obj, materials[mat_key])
        link_to_collection(obj, tunnel if name.startswith("TUNNEL") else track)

    # Module E
    for name, size, location, mat_key, target in (
        ("TRACKBED_E", (300.0, 3.2, 0.3), (1750.0, 0.0, -0.15), "concrete", track),
        ("RAIL_E_Left", (300.0, 0.07, 0.172), (1750.0, -0.7175, 0.086), "metal", track),
        ("RAIL_E_Right", (300.0, 0.07, 0.172), (1750.0, 0.7175, 0.086), "metal", track),
        ("BARRIER_E_Left", (150.0, 0.20, 3.5), (1825.0, -3.6, 1.75), "concrete", structures),
        ("BARRIER_E_Right", (150.0, 0.20, 3.5), (1825.0, 3.6, 1.75), "concrete", structures),
        ("WIRE_E_Catenary", (150.0, 0.02, 0.02), (1825.0, -0.2, 5.5), "copper", catenary),
    ):
        obj = add_box(name, size, location)
        assign_material(obj, materials[mat_key])
        link_to_collection(obj, target)
    for idx, x in enumerate((1770.0, 1830.0, 1890.0), start=1):
        pole = add_cylinder(f"POLE_E_{idx:02d}", 0.15, 7.0, (x, -2.5, 3.5), vertices=12)
        assign_material(pole, materials["metal"])
        link_to_collection(pole, catenary)
    for side, y in (("Left", -5.25), ("Right", 5.25)):
        for step_idx, (x, height) in enumerate(((1625.0, 7.5), (1675.0, 5.0), (1725.0, 3.0)), start=1):
            wall = add_box(f"STEEPWALL_E_{side}_{step_idx}", (50.0, 0.5, height), (x, y, height / 2.0))
            assign_material(wall, materials["granite"])
            link_to_collection(wall, structures)

    # Module F
    for name, size, location, mat_key, target in (
        ("VIADUCT_F_Deck", (1100.0, 12.0, 2.0), (2450.0, 0.0, 11.0), "concrete", structures),
        ("TRACKBED_F", (1100.0, 3.2, 0.3), (2450.0, 0.0, 11.85), "concrete", track),
        ("RAIL_F_Left", (1100.0, 0.07, 0.172), (2450.0, -0.7175, 12.086), "metal", track),
        ("RAIL_F_Right", (1100.0, 0.07, 0.172), (2450.0, 0.7175, 12.086), "metal", track),
        ("PARAPET_F_Left", (1100.0, 0.25, 1.2), (2450.0, -5.875, 12.6), "concrete", structures),
        ("PARAPET_F_Right", (1100.0, 0.25, 1.2), (2450.0, 5.875, 12.6), "concrete", structures),
        ("BARRIER_F_Left", (1100.0, 0.20, 3.5), (2450.0, -3.6, 13.75), "concrete", structures),
        ("BARRIER_F_Right", (1100.0, 0.20, 3.5), (2450.0, 3.6, 13.75), "concrete", structures),
        ("WIRE_F_Catenary", (1100.0, 0.02, 0.02), (2450.0, -0.2, 17.5), "copper", catenary),
    ):
        obj = add_box(name, size, location)
        assign_material(obj, materials[mat_key])
        link_to_collection(obj, target)
    for idx in range(22):
        pier = add_box(f"PIER_F_{idx + 1:02d}", (3.0, 6.0, 10.0), (1925.0 + 50.0 * idx, 0.0, 5.0))
        assign_material(pier, materials["concrete"])
        link_to_collection(pier, structures)
    for idx in range(18):
        pole = add_cylinder(f"POLE_F_{idx + 1:02d}", 0.15, 7.0, (1930.0 + 60.0 * idx, -2.5, 15.5), vertices=12)
        assign_material(pole, materials["metal"])
        link_to_collection(pole, catenary)

    gnb_positions = build_base_stations(config, collections["BaseStation"], materials)
    train_reference = build_train_unified(config, collections["Train"], materials)
    metadata = {
        "scene_type": "unified_3000m",
        "track_centerline_start_m": [0.0, 0.0, unified_trajectory_samples(config)[0][2]],
        "track_centerline_end_m": [3000.0, 0.0, unified_trajectory_samples(config)[-1][2]],
        "modules": unified_modules(),
        "gnb_position_m": list(active_base_station(config)["position_m"]),
        "all_gnb_positions_m": [list(pos) for pos in gnb_positions],
        "train_reference_position_m": list(train_reference),
        "train_dimensions_m": {
            "length_m": config.get("train", {}).get("length_m", 25.0),
            "width_m": config.get("train", {}).get("width_m", 3.4),
            "body_height_m": config.get("train", {}).get("body_height_m", 3.8),
        },
        "rx_trajectory_samples": [list(sample) for sample in unified_trajectory_samples(config)],
    }
    return metadata


def build_legacy_scene(config, collections, materials):
    if not is_tunnel_scenario(config):
        build_ground_legacy(config, collections["Ground"], materials)
    build_track_legacy(config, collections["Track"], materials)
    if is_tunnel_scenario(config):
        build_tunnel_legacy(config, collections["Tunnel"], materials)
    else:
        build_barriers_legacy(config, collections["Structures"], materials)
        build_catenary_legacy(config, collections["Catenary"], materials)
    gnb_positions = build_base_stations(config, collections["BaseStation"], materials)
    train_reference = build_train_legacy(config, collections["Train"], materials)
    metadata = {
        "track_centerline_start_m": [-config["scene"]["length_m"] / 2.0, 0.0, config["train"]["receiver_height_m"]],
        "track_centerline_end_m": [config["scene"]["length_m"] / 2.0, 0.0, config["train"]["receiver_height_m"]],
        "gnb_position_m": list(active_base_station(config)["position_m"]),
        "all_gnb_positions_m": [list(pos) for pos in gnb_positions],
        "train_reference_position_m": list(train_reference),
        "train_dimensions_m": {
            "length_m": config.get("train", {}).get("length_m", 25.0),
            "width_m": config.get("train", {}).get("width_m", 3.2),
            "body_height_m": config.get("train", {}).get("body_height_m", 3.6),
        },
    }
    return metadata


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    output_paths = resolve_output_paths(config)

    clear_scene()
    configure_scene_units()

    collections = {
        "Ground": ensure_collection("Ground"),
        "Track": ensure_collection("Track"),
        "Structures": ensure_collection("Structures"),
        "Catenary": ensure_collection("Catenary"),
        "BaseStation": ensure_collection("BaseStation"),
        "Train": ensure_collection("Train"),
        "Tunnel": ensure_collection("Tunnel"),
    }
    materials = {
        "metal": create_principled_material("Metal", (0.55, 0.57, 0.6, 1.0), 0.95, 0.18, "conductor"),
        "concrete": create_principled_material("Concrete", (0.62, 0.62, 0.6, 1.0), 0.0, 0.75, "diffuse"),
        "ground": create_principled_material("Ground", (0.35, 0.4, 0.27, 1.0), 0.0, 0.95, "diffuse"),
        "granite": create_principled_material("Granite", (0.48, 0.5, 0.54, 1.0), 0.0, 0.78, "diffuse"),
        "copper": create_principled_material("Copper", (0.77, 0.47, 0.22, 1.0), 1.0, 0.22, "conductor"),
        "train_body": create_principled_material("TrainBody", (0.92, 0.94, 0.97, 1.0), 0.15, 0.32, "diffuse"),
        "train_window": create_principled_material("TrainWindow", (0.16, 0.32, 0.52, 1.0), 0.35, 0.08, "diffuse"),
    }

    if is_unified_scenario(config):
        metadata = build_unified_scene(config, collections, materials)
        configure_large_scene_view(center_x=1500.0, center_y=0.0, center_z=10.0, distance=2200.0, clip_end=12000.0)
    else:
        metadata = build_legacy_scene(config, collections, materials)
        configure_large_scene_view(center_x=0.0, center_y=0.0, center_z=5.0, distance=900.0, clip_end=4000.0)
        if is_tunnel_scenario(config):
            metadata["tunnel_height_m"] = config["tunnel"]["inner_height_m"]
        else:
            metadata["barrier_inner_planes_y_m"] = [
                config["noise_barriers"]["center_offset_m"] - config["noise_barriers"]["thickness_m"] / 2.0,
                -config["noise_barriers"]["center_offset_m"] + config["noise_barriers"]["thickness_m"] / 2.0,
            ]

    bpy.ops.wm.save_as_mainfile(filepath=str(output_paths["blend_file"]))
    dump_json(output_paths["scene_metadata"], metadata)
    print(f"Saved Blender scene to {output_paths['blend_file']}")
    print(f"Saved scene metadata to {output_paths['scene_metadata']}")


if __name__ == "__main__":
    main()
