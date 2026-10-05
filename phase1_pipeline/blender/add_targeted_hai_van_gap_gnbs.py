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
    parser = argparse.ArgumentParser(description="Add targeted trackside gNBs at Hai Van coverage gaps.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--indices", default="74,101")
    parser.add_argument("--offset-m", type=float, default=18.0)
    parser.add_argument("--height-m", type=float, default=48.0)
    return parser.parse_args(argv)


def make_material() -> bpy.types.Material:
    material = bpy.data.materials.get("GNB_Metal_Blue") or bpy.data.materials.new("GNB_Metal_Blue")
    material.diffuse_color = (0.03, 0.20, 0.95, 1.0)
    material["sionna_bsdf_id"] = "mat-vn_metal"
    material["mitsuba_bsdf_id"] = "mat-vn_metal"
    return material


def add_cylinder(name: str, location: Vector, radius: float, depth: float, material: bpy.types.Material) -> None:
    bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=radius, depth=depth, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(material)
    obj["sionna_bsdf_id"] = "mat-vn_metal"


def add_box(name: str, location: Vector, dimensions: tuple[float, float, float], yaw_rad: float, material: bpy.types.Material) -> None:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    obj.rotation_euler[2] = yaw_rad
    obj.data.materials.append(material)
    obj["sionna_bsdf_id"] = "mat-vn_metal"
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)


def lateral(tangent: Vector) -> Vector:
    return Vector((-tangent.y, tangent.x, 0.0)).normalized()


def nearest_cardinal_facing(direction: Vector) -> str:
    if abs(direction.x) >= abs(direction.y):
        return "x+" if direction.x >= 0.0 else "x-"
    return "y+" if direction.y >= 0.0 else "y-"


def station_letter(index: int) -> str:
    if index < 26:
        return chr(65 + index)
    return f"X{index}"


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    output_paths = resolve_output_paths(config)
    metadata_path = output_paths["scene_metadata"]
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    samples = [Vector((float(p[0]), float(p[1]), float(p[2]))) for p in metadata["rx_trajectory_samples"]]
    rx_height = float(config.get("train", {}).get("receiver_height_m", 6.0))
    indices = [int(item.strip()) for item in args.indices.split(",") if item.strip()]
    material = make_material()
    positions = metadata.setdefault("all_gnb_positions_m", [])
    facings = metadata.setdefault("all_gnb_facing", [])
    added = []

    for add_idx, sample_idx in enumerate(indices):
        if sample_idx <= 0 or sample_idx >= len(samples) - 1:
            raise ValueError(f"Target sample index {sample_idx} cannot provide a tangent.")
        center = samples[sample_idx]
        prev_point = samples[sample_idx - 1]
        next_point = samples[sample_idx + 1]
        tangent = Vector((next_point.x - prev_point.x, next_point.y - prev_point.y, 0.0)).normalized()
        side_sign = -1.0 if add_idx % 2 == 0 else 1.0
        side = lateral(tangent) * (args.offset_m * side_sign)
        ground_z = center.z - rx_height
        base = Vector((center.x + side.x, center.y + side.y, ground_z))
        height = float(args.height_m)
        station_index = len(positions)
        letter = station_letter(station_index)
        to_track = Vector((center.x - base.x, center.y - base.y, 0.0)).normalized()
        add_cylinder(f"GNB_{letter}_Mast", Vector((base.x, base.y, ground_z + height / 2.0)), 0.22, height, material)
        add_box(f"GNB_{letter}_Antenna", Vector((base.x, base.y, ground_z + height)), (0.9, 0.28, 1.35), math.atan2(to_track.y, to_track.x), material)
        positions.append([base.x, base.y, ground_z + height])
        facings.append(nearest_cardinal_facing(to_track))
        added.append({"name": f"GNB_{letter}", "sample_index": sample_idx, "position_m": positions[-1]})

    metadata["targeted_gap_gnbs"] = added
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    output_paths["blend_file"].with_suffix(".report.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    bpy.ops.wm.save_as_mainfile(filepath=str(output_paths["blend_file"]))
    print(f"Added {len(added)} targeted Hai Van gap gNBs: {added}")


if __name__ == "__main__":
    main()
