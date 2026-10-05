from __future__ import annotations

import argparse
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from phase1_pipeline.common import dump_json, ensure_parent, load_config, resolve_output_paths
from phase1_pipeline.scenarios import (
    active_base_station,
    all_base_stations,
    is_tunnel_scenario,
    is_unified_scenario,
    unified_modules,
    unified_trajectory_samples,
)


def safe_text(value: object) -> str:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return str(value).encode(encoding, errors="backslashreplace").decode(encoding, errors="replace")


def safe_name(name: str) -> str:
    return "".join(char if char.isalnum() or char in ("_", "-") else "_" for char in name)


def box_vertices(center: Tuple[float, float, float], size: Tuple[float, float, float]) -> Tuple[List[Tuple[float, float, float]], List[Tuple[int, int, int]]]:
    cx, cy, cz = center
    lx, ly, lz = size
    hx, hy, hz = lx / 2.0, ly / 2.0, lz / 2.0
    vertices = [
        (cx - hx, cy - hy, cz - hz),
        (cx + hx, cy - hy, cz - hz),
        (cx + hx, cy + hy, cz - hz),
        (cx - hx, cy + hy, cz - hz),
        (cx - hx, cy - hy, cz + hz),
        (cx + hx, cy - hy, cz + hz),
        (cx + hx, cy + hy, cz + hz),
        (cx - hx, cy + hy, cz + hz),
    ]
    faces = [
        (1, 2, 3), (1, 3, 4),
        (5, 6, 7), (5, 7, 8),
        (1, 2, 6), (1, 6, 5),
        (2, 3, 7), (2, 7, 6),
        (3, 4, 8), (3, 8, 7),
        (4, 1, 5), (4, 5, 8),
    ]
    return vertices, faces


def cylinder_vertices(
    center: Tuple[float, float, float],
    radius: float,
    depth: float,
    segments: int = 16,
    axis: str = "z",
) -> Tuple[List[Tuple[float, float, float]], List[Tuple[int, int, int]]]:
    cx, cy, cz = center
    half = depth / 2.0
    bottom = []
    top = []
    for idx in range(segments):
        angle = 2.0 * math.pi * idx / segments
        ca = radius * math.cos(angle)
        sa = radius * math.sin(angle)
        if axis == "y":
            bottom.append((cx + ca, cy - half, cz + sa))
            top.append((cx + ca, cy + half, cz + sa))
        elif axis == "x":
            bottom.append((cx - half, cy + ca, cz + sa))
            top.append((cx + half, cy + ca, cz + sa))
        else:
            bottom.append((cx + ca, cy + sa, cz - half))
            top.append((cx + ca, cy + sa, cz + half))
    vertices = bottom + top + [center]
    faces: List[Tuple[int, int, int]] = []
    for idx in range(segments):
        nidx = (idx + 1) % segments
        b0 = idx + 1
        b1 = nidx + 1
        t0 = idx + segments + 1
        t1 = nidx + segments + 1
        faces.extend([(b0, b1, t1), (b0, t1, t0)])
    return vertices, faces


def write_obj(path: Path, vertices: Iterable[Tuple[float, float, float]], faces: Iterable[Tuple[int, int, int]]) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8") as handle:
        for vx, vy, vz in vertices:
            handle.write(f"v {vx:.6f} {vy:.6f} {vz:.6f}\n")
        for a, b, c in faces:
            handle.write(f"f {a} {b} {c}\n")


def material_bsdf(bsdf_id: str, material_type: str, thickness_m: float, scattering_coefficient: float = 0.0, xpd_coefficient: float = 0.0) -> ET.Element:
    bsdf = ET.Element("bsdf", {"type": "itu-radio-material", "id": bsdf_id})
    ET.SubElement(bsdf, "string", {"name": "type", "value": material_type})
    ET.SubElement(bsdf, "float", {"name": "thickness", "value": f"{thickness_m:.3f}"})
    ET.SubElement(bsdf, "float", {"name": "scattering_coefficient", "value": f"{scattering_coefficient:.3f}"})
    ET.SubElement(bsdf, "float", {"name": "xpd_coefficient", "value": f"{xpd_coefficient:.3f}"})
    return bsdf


def material_library() -> Dict[str, Dict[str, float | str]]:
    return {
        "mat-itu_concrete": {"type": "concrete", "thickness_m": 0.30, "scattering_coefficient": 0.12, "xpd_coefficient": 0.15},
        "mat-itu_concrete_rough": {"type": "concrete", "thickness_m": 0.35, "scattering_coefficient": 0.25, "xpd_coefficient": 0.20},
        "mat-itu_metal": {"type": "metal", "thickness_m": 0.01, "scattering_coefficient": 0.03, "xpd_coefficient": 0.05},
        "mat-itu_glass": {"type": "glass", "thickness_m": 0.02, "scattering_coefficient": 0.02, "xpd_coefficient": 0.05},
        "mat-itu_marble": {"type": "marble", "thickness_m": 0.40, "scattering_coefficient": 0.18, "xpd_coefficient": 0.15},
    }


def add_shape(root: ET.Element, shape_id: str, filename: Path, bsdf_id: str, xml_dir: Path) -> None:
    shape = ET.SubElement(root, "shape", {"type": "obj", "id": f"mesh-{safe_name(shape_id)}"})
    ET.SubElement(shape, "string", {"name": "filename", "value": filename.relative_to(xml_dir).as_posix()})
    ET.SubElement(shape, "boolean", {"name": "face_normals", "value": "true"})
    ET.SubElement(shape, "ref", {"id": bsdf_id, "name": "bsdf"})


def facing_offset(facing: str, distance: float) -> Tuple[float, float, float]:
    mapping = {
        "x+": (distance, 0.0, 0.0),
        "x-": (-distance, 0.0, 0.0),
        "y+": (0.0, distance, 0.0),
        "y-": (0.0, -distance, 0.0),
    }
    return mapping.get(facing, (0.0, -distance, 0.0))


def append_box(objects: List[Tuple[str, Path, str]], mesh_dir: Path, name: str, center, size, bsdf_id: str) -> None:
    path = mesh_dir / f"{safe_name(name)}.obj"
    verts, faces = box_vertices(center, size)
    write_obj(path, verts, faces)
    objects.append((name, path, bsdf_id))


def append_cylinder(objects: List[Tuple[str, Path, str]], mesh_dir: Path, name: str, center, radius: float, depth: float, bsdf_id: str, axis: str = "z") -> None:
    path = mesh_dir / f"{safe_name(name)}.obj"
    verts, faces = cylinder_vertices(center, radius, depth, axis=axis)
    write_obj(path, verts, faces)
    objects.append((name, path, bsdf_id))


def append_tunnel_clutter(config: Dict, mesh_dir: Path, objects: List[Tuple[str, Path, str]]) -> None:
    density = str(config.get("ray_tracing", {}).get("tunnel_clutter_density", "medium")).lower()
    if density == "low":
        step = 75.0
    elif density == "high":
        step = 30.0
    else:
        step = 50.0

    append_box(objects, mesh_dir, "TUNNEL_D_CableTrayLeft", (1450.0, -4.55, 6.85), (300.0, 0.30, 0.18), "mat-itu_metal")
    append_box(objects, mesh_dir, "TUNNEL_D_CableTrayRight", (1450.0, 4.55, 6.85), (300.0, 0.30, 0.18), "mat-itu_metal")

    index = 1
    x = 1325.0
    while x <= 1575.0:
        append_box(objects, mesh_dir, f"TUNNEL_D_ServiceBoxLeft_{index:02d}", (x, -4.55, 1.35), (1.20, 0.45, 1.80), "mat-itu_metal")
        append_box(objects, mesh_dir, f"TUNNEL_D_ServiceBoxRight_{index:02d}", (x, 4.55, 1.35), (1.20, 0.45, 1.80), "mat-itu_metal")
        x += step
        index += 1

    for portal_x in (1300.0, 1600.0):
        portal_tag = f"{int(portal_x)}"
        append_box(objects, mesh_dir, f"PORTAL_{portal_tag}_LeftJamb", (portal_x, -4.95, 3.75), (0.80, 0.40, 7.50), "mat-itu_concrete_rough")
        append_box(objects, mesh_dir, f"PORTAL_{portal_tag}_RightJamb", (portal_x, 4.95, 3.75), (0.80, 0.40, 7.50), "mat-itu_concrete_rough")
        append_box(objects, mesh_dir, f"PORTAL_{portal_tag}_Lintel", (portal_x, 0.0, 7.10), (0.80, 10.30, 0.70), "mat-itu_concrete_rough")


def append_base_station_objects(config: Dict, mesh_dir: Path, objects: List[Tuple[str, Path, str]]) -> List[Tuple[float, float, float]]:
    stations = []
    for idx, gnb_cfg in enumerate(all_base_stations(config)):
        label = safe_name(str(gnb_cfg.get("name", f"gnb_{idx}")))
        mast_x, mast_y, mast_z = [float(v) for v in gnb_cfg["position_m"]]
        append_cylinder(objects, mesh_dir, f"{label}_mast", (mast_x, mast_y, float(gnb_cfg["height_m"]) / 2.0), float(gnb_cfg["mast_radius_m"]), float(gnb_cfg["height_m"]), "mat-itu_metal")
        antenna_size = tuple(float(v) for v in gnb_cfg["antenna_size_m"])
        dx, dy, dz = facing_offset(str(gnb_cfg.get("facing", "y-")), antenna_size[1] / 2.0)
        append_box(objects, mesh_dir, f"{label}_antenna", (mast_x + dx, mast_y + dy, mast_z + dz), antenna_size, "mat-itu_metal")
        stations.append((mast_x, mast_y, mast_z))
    return stations


def build_unified_scene(config: Dict, output_paths: Dict[str, Path]) -> None:
    mesh_dir = output_paths["mesh_dir"]
    objects: List[Tuple[str, Path, str]] = []
    train_cfg = config["train"]
    include_train_in_rt_scene = bool(config.get("ray_tracing", {}).get("include_train_in_rt_scene", False))

    append_box(objects, mesh_dir, "GROUND_OUTDOOR", (1500.0, 0.0, -0.3), (3000.0, 200.0, 0.6), "mat-itu_concrete_rough")

    # Module A
    append_box(objects, mesh_dir, "VIADUCT_A_Deck", (350.0, 0.0, 11.0), (700.0, 12.0, 2.0), "mat-itu_concrete")
    append_box(objects, mesh_dir, "TRACKBED_A", (350.0, 0.0, 11.85), (700.0, 3.2, 0.3), "mat-itu_concrete")
    append_box(objects, mesh_dir, "RAIL_A_Left", (350.0, -0.7175, 12.086), (700.0, 0.07, 0.172), "mat-itu_metal")
    append_box(objects, mesh_dir, "RAIL_A_Right", (350.0, 0.7175, 12.086), (700.0, 0.07, 0.172), "mat-itu_metal")
    append_box(objects, mesh_dir, "PARAPET_A_Left", (350.0, -5.875, 12.6), (700.0, 0.25, 1.2), "mat-itu_concrete")
    append_box(objects, mesh_dir, "PARAPET_A_Right", (350.0, 5.875, 12.6), (700.0, 0.25, 1.2), "mat-itu_concrete")
    append_box(objects, mesh_dir, "BARRIER_A_Left", (350.0, -3.6, 13.75), (700.0, 0.20, 3.5), "mat-itu_concrete")
    append_box(objects, mesh_dir, "BARRIER_A_Right", (350.0, 3.6, 13.75), (700.0, 0.20, 3.5), "mat-itu_concrete")
    append_box(objects, mesh_dir, "WIRE_A_Catenary", (350.0, -0.2, 17.5), (700.0, 0.02, 0.02), "mat-itu_metal")
    for idx in range(14):
        x = 50.0 * (idx + 1)
        append_box(objects, mesh_dir, f"PIER_A_{idx + 1:02d}", (x, 0.0, 5.0), (3.0, 6.0, 10.0), "mat-itu_concrete")
    for idx in range(12):
        x = 30.0 + 60.0 * idx
        append_cylinder(objects, mesh_dir, f"POLE_A_{idx + 1:02d}", (x, -2.5, 15.5), 0.15, 7.0, "mat-itu_metal")

    # Module B
    append_box(objects, mesh_dir, "TRACKBED_B", (900.0, 0.0, -0.15), (400.0, 3.2, 0.3), "mat-itu_concrete")
    append_box(objects, mesh_dir, "RAIL_B_Left", (900.0, -0.7175, 0.086), (400.0, 0.07, 0.172), "mat-itu_metal")
    append_box(objects, mesh_dir, "RAIL_B_Right", (900.0, 0.7175, 0.086), (400.0, 0.07, 0.172), "mat-itu_metal")
    append_box(objects, mesh_dir, "BARRIER_B_Left", (900.0, -3.6, 1.75), (400.0, 0.20, 3.5), "mat-itu_concrete")
    append_box(objects, mesh_dir, "BARRIER_B_Right", (900.0, 3.6, 1.75), (400.0, 0.20, 3.5), "mat-itu_concrete")
    append_box(objects, mesh_dir, "WIRE_B_Catenary", (900.0, -0.2, 5.5), (400.0, 0.02, 0.02), "mat-itu_metal")
    for idx in range(7):
        append_cylinder(objects, mesh_dir, f"POLE_B_{idx + 1:02d}", (700.0 + 60.0 * idx, -2.5, 3.5), 0.15, 7.0, "mat-itu_metal")

    # Module C
    append_box(objects, mesh_dir, "TRACKBED_C", (1200.0, 0.0, -0.15), (200.0, 3.2, 0.3), "mat-itu_concrete")
    append_box(objects, mesh_dir, "RAIL_C_Left", (1200.0, -0.7175, 0.086), (200.0, 0.07, 0.172), "mat-itu_metal")
    append_box(objects, mesh_dir, "RAIL_C_Right", (1200.0, 0.7175, 0.086), (200.0, 0.07, 0.172), "mat-itu_metal")
    append_box(objects, mesh_dir, "BARRIER_C_Left", (1150.0, -3.6, 1.75), (100.0, 0.20, 3.5), "mat-itu_concrete")
    append_box(objects, mesh_dir, "BARRIER_C_Right", (1150.0, 3.6, 1.75), (100.0, 0.20, 3.5), "mat-itu_concrete")
    append_cylinder(objects, mesh_dir, "POLE_C_01", (1120.0, -2.5, 3.5), 0.15, 7.0, "mat-itu_metal")
    append_cylinder(objects, mesh_dir, "POLE_C_02", (1180.0, -2.5, 3.5), 0.15, 7.0, "mat-itu_metal")
    for side, y in (("Left", -5.25), ("Right", 5.25)):
        for step_idx, (x, height) in enumerate(((1175.0, 3.0), (1225.0, 5.0), (1275.0, 7.5)), start=1):
            append_box(objects, mesh_dir, f"STEEPWALL_C_{side}_{step_idx}", (x, y, height / 2.0), (50.0, 0.5, height), "mat-itu_marble")

    # Module D
    append_box(objects, mesh_dir, "TUNNEL_D_Floor", (1450.0, 0.0, -0.25), (300.0, 10.0, 0.5), "mat-itu_concrete_rough")
    append_box(objects, mesh_dir, "TUNNEL_D_Ceiling", (1450.0, 0.0, 7.75), (300.0, 10.0, 0.5), "mat-itu_concrete_rough")
    append_box(objects, mesh_dir, "TUNNEL_D_WallLeft", (1450.0, -5.25, 3.75), (300.0, 0.5, 7.5), "mat-itu_concrete_rough")
    append_box(objects, mesh_dir, "TUNNEL_D_WallRight", (1450.0, 5.25, 3.75), (300.0, 0.5, 7.5), "mat-itu_concrete_rough")
    append_box(objects, mesh_dir, "RAIL_D_Left", (1450.0, -0.7175, 0.086), (300.0, 0.07, 0.172), "mat-itu_metal")
    append_box(objects, mesh_dir, "RAIL_D_Right", (1450.0, 0.7175, 0.086), (300.0, 0.07, 0.172), "mat-itu_metal")

    append_tunnel_clutter(config, mesh_dir, objects)

    # Module E
    append_box(objects, mesh_dir, "TRACKBED_E", (1750.0, 0.0, -0.15), (300.0, 3.2, 0.3), "mat-itu_concrete")
    append_box(objects, mesh_dir, "RAIL_E_Left", (1750.0, -0.7175, 0.086), (300.0, 0.07, 0.172), "mat-itu_metal")
    append_box(objects, mesh_dir, "RAIL_E_Right", (1750.0, 0.7175, 0.086), (300.0, 0.07, 0.172), "mat-itu_metal")
    append_box(objects, mesh_dir, "BARRIER_E_Left", (1825.0, -3.6, 1.75), (150.0, 0.20, 3.5), "mat-itu_concrete")
    append_box(objects, mesh_dir, "BARRIER_E_Right", (1825.0, 3.6, 1.75), (150.0, 0.20, 3.5), "mat-itu_concrete")
    append_box(objects, mesh_dir, "WIRE_E_Catenary", (1825.0, -0.2, 5.5), (150.0, 0.02, 0.02), "mat-itu_metal")
    for idx, x in enumerate((1770.0, 1830.0, 1890.0), start=1):
        append_cylinder(objects, mesh_dir, f"POLE_E_{idx:02d}", (x, -2.5, 3.5), 0.15, 7.0, "mat-itu_metal")
    for side, y in (("Left", -5.25), ("Right", 5.25)):
        for step_idx, (x, height) in enumerate(((1625.0, 7.5), (1675.0, 5.0), (1725.0, 3.0)), start=1):
            append_box(objects, mesh_dir, f"STEEPWALL_E_{side}_{step_idx}", (x, y, height / 2.0), (50.0, 0.5, height), "mat-itu_marble")

    # Module F
    append_box(objects, mesh_dir, "VIADUCT_F_Deck", (2450.0, 0.0, 11.0), (1100.0, 12.0, 2.0), "mat-itu_concrete")
    append_box(objects, mesh_dir, "TRACKBED_F", (2450.0, 0.0, 11.85), (1100.0, 3.2, 0.3), "mat-itu_concrete")
    append_box(objects, mesh_dir, "RAIL_F_Left", (2450.0, -0.7175, 12.086), (1100.0, 0.07, 0.172), "mat-itu_metal")
    append_box(objects, mesh_dir, "RAIL_F_Right", (2450.0, 0.7175, 12.086), (1100.0, 0.07, 0.172), "mat-itu_metal")
    append_box(objects, mesh_dir, "PARAPET_F_Left", (2450.0, -5.875, 12.6), (1100.0, 0.25, 1.2), "mat-itu_concrete")
    append_box(objects, mesh_dir, "PARAPET_F_Right", (2450.0, 5.875, 12.6), (1100.0, 0.25, 1.2), "mat-itu_concrete")
    append_box(objects, mesh_dir, "BARRIER_F_Left", (2450.0, -3.6, 13.75), (1100.0, 0.20, 3.5), "mat-itu_concrete")
    append_box(objects, mesh_dir, "BARRIER_F_Right", (2450.0, 3.6, 13.75), (1100.0, 0.20, 3.5), "mat-itu_concrete")
    append_box(objects, mesh_dir, "WIRE_F_Catenary", (2450.0, -0.2, 17.5), (1100.0, 0.02, 0.02), "mat-itu_metal")
    for idx in range(22):
        x = 1925.0 + 50.0 * idx
        append_box(objects, mesh_dir, f"PIER_F_{idx + 1:02d}", (x, 0.0, 5.0), (3.0, 6.0, 10.0), "mat-itu_concrete")
    for idx in range(18):
        x = 1930.0 + 60.0 * idx
        append_cylinder(objects, mesh_dir, f"POLE_F_{idx + 1:02d}", (x, -2.5, 15.5), 0.15, 7.0, "mat-itu_metal")

    gnb_positions = append_base_station_objects(config, mesh_dir, objects)

    trajectory = unified_trajectory_samples(config)
    train_x, train_y, train_z = trajectory[0]
    train_length = float(train_cfg.get("length_m", 25.0))
    train_width = float(train_cfg.get("width_m", 3.4))
    train_height = float(train_cfg.get("body_height_m", 3.8))
    train_body_center = (train_x - 12.5, train_y, train_z - 2.1)
    if include_train_in_rt_scene:
        append_box(objects, mesh_dir, "TRAIN_Body", train_body_center, (train_length, train_width, train_height), "mat-itu_metal")

    root = ET.Element("scene", {"version": "3.0.0"})
    xml_dir = output_paths["mitsuba_xml"].parent
    integrator = ET.SubElement(root, "integrator", {"type": "path"})
    ET.SubElement(integrator, "integer", {"name": "max_depth", "value": "10"})
    emitter = ET.SubElement(root, "emitter", {"type": "constant"})
    ET.SubElement(emitter, "rgb", {"name": "radiance", "value": "0.20,0.20,0.20"})
    sensor = ET.SubElement(root, "sensor", {"type": "perspective"})
    ET.SubElement(sensor, "float", {"name": "fov", "value": "45"})
    film = ET.SubElement(sensor, "film", {"type": "hdrfilm"})
    ET.SubElement(film, "integer", {"name": "width", "value": "1024"})
    ET.SubElement(film, "integer", {"name": "height", "value": "576"})

    for bsdf_id, params in material_library().items():
        root.append(
            material_bsdf(
                bsdf_id,
                str(params["type"]),
                float(params["thickness_m"]),
                float(params["scattering_coefficient"]),
                float(params["xpd_coefficient"]),
            )
        )
    for name, path, bsdf_id in objects:
        add_shape(root, name, path, bsdf_id, xml_dir)

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(output_paths["mitsuba_xml"], encoding="utf-8", xml_declaration=True)

    metadata = {
        "scene_type": "unified_3000m",
        "track_centerline_start_m": [0.0, 0.0, trajectory[0][2]],
        "track_centerline_end_m": [3000.0, 0.0, trajectory[-1][2]],
        "modules": unified_modules(),
        "gnb_position_m": list(active_base_station(config)["position_m"]),
        "all_gnb_positions_m": [list(pos) for pos in gnb_positions],
        "train_reference_position_m": list(train_body_center),
        "train_dimensions_m": {"length_m": train_length, "width_m": train_width, "body_height_m": train_height},
        "rx_trajectory_samples": [[x, y, z] for x, y, z in trajectory],
    }
    dump_json(output_paths["scene_metadata"], metadata)


def build_legacy_scene(config: Dict, output_paths: Dict[str, Path]) -> None:
    mesh_dir = output_paths["mesh_dir"]
    scene_cfg = config["scene"]
    rail_cfg = config["railway"]
    barrier_cfg = config["noise_barriers"]
    train_cfg = config["train"]
    include_train_in_rt_scene = bool(config.get("ray_tracing", {}).get("include_train_in_rt_scene", False))

    length = float(scene_cfg["length_m"])
    width = float(scene_cfg["width_m"])
    rail_height = float(rail_cfg["rail_height_m"])
    rail_width = float(rail_cfg["rail_width_m"])
    gauge = float(rail_cfg["gauge_m"])
    barrier_offset = float(barrier_cfg["center_offset_m"])
    barrier_height = float(barrier_cfg["height_m"])
    barrier_thickness = float(barrier_cfg["thickness_m"])

    objects: List[Tuple[str, Path, str]] = []
    if not is_tunnel_scenario(config):
        append_box(objects, mesh_dir, "ground", (0.0, 0.0, -0.05), (length, width, 0.1), "mat-itu_concrete")

    rail_half = gauge / 2.0
    append_box(objects, mesh_dir, "rail_left", (0.0, rail_half, rail_height / 2.0), (length, rail_width, rail_height), "mat-itu_metal")
    append_box(objects, mesh_dir, "rail_right", (0.0, -rail_half, rail_height / 2.0), (length, rail_width, rail_height), "mat-itu_metal")
    append_box(objects, mesh_dir, "barrier_north", (0.0, barrier_offset, barrier_height / 2.0), (length, barrier_thickness, barrier_height), "mat-itu_concrete")
    append_box(objects, mesh_dir, "barrier_south", (0.0, -barrier_offset, barrier_height / 2.0), (length, barrier_thickness, barrier_height), "mat-itu_concrete")

    if is_tunnel_scenario(config):
        tunnel_cfg = config["tunnel"]
        inner_width = float(tunnel_cfg["inner_width_m"])
        inner_height = float(tunnel_cfg["inner_height_m"])
        wall_thickness = float(tunnel_cfg.get("wall_thickness_m", 0.35))
        tunnel_length = float(tunnel_cfg["length_m"])
        tunnel_center_x = float(tunnel_cfg.get("center_x_m", 0.0))
        append_box(objects, mesh_dir, "tunnel_floor", (tunnel_center_x, 0.0, -wall_thickness / 2.0), (tunnel_length + wall_thickness * 2.0, inner_width + wall_thickness * 2.0, wall_thickness), "mat-itu_concrete")
        append_box(objects, mesh_dir, "tunnel_wall_north", (tunnel_center_x, inner_width / 2.0 + wall_thickness / 2.0, inner_height / 2.0), (tunnel_length, wall_thickness, inner_height), "mat-itu_concrete")
        append_box(objects, mesh_dir, "tunnel_wall_south", (tunnel_center_x, -inner_width / 2.0 - wall_thickness / 2.0, inner_height / 2.0), (tunnel_length, wall_thickness, inner_height), "mat-itu_concrete")
        append_box(objects, mesh_dir, "tunnel_roof", (tunnel_center_x, 0.0, inner_height + wall_thickness / 2.0), (tunnel_length, inner_width + wall_thickness * 2.0, wall_thickness), "mat-itu_concrete")
    else:
        catenary_cfg = config["catenary"]
        pole_spacing = float(catenary_cfg["pole_spacing_m"])
        pole_height = float(catenary_cfg["pole_height_m"])
        pole_offset = float(catenary_cfg["pole_offset_m"])
        pole_radius = float(catenary_cfg["pole_radius_m"])
        pole_count = int(length / pole_spacing) + 1
        for idx in range(pole_count):
            x = -length / 2.0 + idx * pole_spacing
            append_cylinder(objects, mesh_dir, f"catenary_pole_{idx:03d}", (x, pole_offset, pole_height / 2.0), pole_radius, pole_height, "mat-itu_metal")

    gnb_positions = append_base_station_objects(config, mesh_dir, objects)

    train_length = float(train_cfg.get("length_m", 25.0))
    train_width = float(train_cfg.get("width_m", 3.2))
    train_height = float(train_cfg.get("body_height_m", 3.6))
    wheel_radius = float(train_cfg.get("wheel_radius_m", 0.42))
    x = -length / 2.0 + train_length / 2.0 + 4.0
    y = float(train_cfg.get("lateral_offset_m", 0.0))
    z = wheel_radius + train_height / 2.0
    if include_train_in_rt_scene:
        append_box(objects, mesh_dir, "train_body", (x, y, z), (train_length, train_width, train_height), "mat-itu_metal")

    root = ET.Element("scene", {"version": "3.0.0"})
    xml_dir = output_paths["mitsuba_xml"].parent
    integrator = ET.SubElement(root, "integrator", {"type": "path"})
    ET.SubElement(integrator, "integer", {"name": "max_depth", "value": "8"})
    emitter = ET.SubElement(root, "emitter", {"type": "constant"})
    ET.SubElement(emitter, "rgb", {"name": "radiance", "value": "0.25,0.25,0.25"})
    sensor = ET.SubElement(root, "sensor", {"type": "perspective"})
    ET.SubElement(sensor, "float", {"name": "fov", "value": "45"})
    film = ET.SubElement(sensor, "film", {"type": "hdrfilm"})
    ET.SubElement(film, "integer", {"name": "width", "value": "800"})
    ET.SubElement(film, "integer", {"name": "height", "value": "450"})
    for bsdf_id in ("mat-itu_concrete", "mat-itu_concrete_rough", "mat-itu_metal", "mat-itu_glass", "mat-itu_marble"):
        params = material_library()[bsdf_id]
        root.append(
            material_bsdf(
                bsdf_id,
                str(params["type"]),
                float(params["thickness_m"]),
                float(params["scattering_coefficient"]),
                float(params["xpd_coefficient"]),
            )
        )
    for name, path, bsdf_id in objects:
        add_shape(root, name, path, bsdf_id, xml_dir)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(output_paths["mitsuba_xml"], encoding="utf-8", xml_declaration=True)

    metadata = {
        "track_centerline_start_m": [-config["scene"]["length_m"] / 2.0, 0.0, config["train"]["receiver_height_m"]],
        "track_centerline_end_m": [config["scene"]["length_m"] / 2.0, 0.0, config["train"]["receiver_height_m"]],
        "gnb_position_m": list(active_base_station(config)["position_m"]),
        "all_gnb_positions_m": [list(pos) for pos in gnb_positions],
        "train_reference_position_m": [x, y, z],
    }
    dump_json(output_paths["scene_metadata"], metadata)


def build_scene(config: Dict, output_paths: Dict[str, Path]) -> None:
    if is_unified_scenario(config):
        build_unified_scene(config, output_paths)
        return
    build_legacy_scene(config, output_paths)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a Mitsuba scene directly from config without Blender.")
    parser.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parents[2] / "phase1_pipeline" / "config" / "config.yaml"),
        help="Path to the pipeline YAML configuration file.",
    )
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = argv[1:]
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    output_paths = resolve_output_paths(config)
    build_scene(config, output_paths)
    print(f"Exported fallback Mitsuba XML to {safe_text(output_paths['mitsuba_xml'])}")


if __name__ == "__main__":
    main()
