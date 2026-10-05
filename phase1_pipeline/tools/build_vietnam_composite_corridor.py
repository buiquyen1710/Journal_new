from __future__ import annotations

import argparse
import gzip
import json
import math
import struct
import sys
from pathlib import Path

import bpy
from mathutils import Vector


MODULES = [
    {
        "id": "do_thi_day_dac_GiaiPhong-GiapBat",
        "label": "Urban dense: Giai Phong - Giap Bat",
        "length_m": 3000.0,
        "half_width_m": 450.0,
        "gnb_spacing_m": 750.0,
        "gnb_offset_m": 65.0,
    },
    {
        "id": "do_thi_cau_song_LongBien-GiaLam",
        "label": "River bridge urban: Long Bien - Gia Lam",
        "length_m": 3000.0,
        "half_width_m": 550.0,
        "gnb_spacing_m": 1000.0,
        "gnb_offset_m": 80.0,
    },
    {
        "id": "dong_bang_cong_nghiep_HaiDuong-PhuThai",
        "label": "Delta industrial: Hai Duong - Phu Thai",
        "length_m": 4000.0,
        "half_width_m": 500.0,
        "gnb_spacing_m": 1200.0,
        "gnb_offset_m": 80.0,
    },
    {
        "id": "do_thi_cang_bien_HaiPhong-ThuongLy",
        "label": "Port urban: Hai Phong - Thuong Ly",
        "length_m": 3500.0,
        "half_width_m": 520.0,
        "gnb_spacing_m": 850.0,
        "gnb_offset_m": 75.0,
    },
    {
        "id": "dam_pha_ven_bien_LangCo-HaiVanBac",
        "label": "Coastal lagoon: Lang Co - Hai Van Bac",
        "length_m": 4000.0,
        "half_width_m": 650.0,
        "gnb_spacing_m": 1500.0,
        "gnb_offset_m": 100.0,
    },
    {
        "id": "deo_nui_ven_bien_HaiVanBac-HaiVanNam",
        "label": "Coastal mountain pass: Hai Van Bac - Hai Van Nam",
        "length_m": 7500.0,
        "half_width_m": 850.0,
        "gnb_spacing_m": 1100.0,
        "gnb_offset_m": 90.0,
        "dem_bbox": [16.120, 108.080, 16.225, 108.175],
    },
]


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene-dir", required=True)
    parser.add_argument("--dem-hgt-gz", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--report", required=True)
    return parser.parse_args(argv)


def make_material(name: str, color, bsdf: str) -> bpy.types.Material:
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = color
    mat["sionna_bsdf_id"] = bsdf
    return mat


def apply_rt_tags() -> None:
    for obj in bpy.context.scene.objects:
        if obj.type not in {"MESH", "CURVE"}:
            continue
        text = " ".join(
            part.lower()
            for part in (
                obj.name,
                obj.data.name if getattr(obj, "data", None) else "",
                obj.active_material.name if obj.active_material else "",
            )
        )
        if "gnb" in text or "antenna" in text or "rail" in text or "track" in text:
            obj["sionna_bsdf_id"] = "mat-vn_metal"
        elif "water" in text or "river" in text or "lake" in text or "dam" in text:
            obj["sionna_bsdf_id"] = "mat-vn_wet_ground"
        elif "forest" in text or "tree" in text or "vegetation" in text or "wood" in text:
            obj["sionna_bsdf_id"] = "mat-vn_vegetation"
        elif "terrain" in text or "mountain" in text or "hai_van_dem" in text:
            obj["sionna_bsdf_id"] = "mat-vn_granite"
        else:
            obj["sionna_bsdf_id"] = "mat-vn_concrete"


def object_world_bbox(obj: bpy.types.Object) -> list[Vector]:
    if not hasattr(obj, "bound_box"):
        return []
    try:
        return [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    except Exception:
        return []


def objects_bbox(objects: list[bpy.types.Object]) -> tuple[float, float, float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    for obj in objects:
        if obj.type not in {"MESH", "CURVE"}:
            continue
        for p in object_world_bbox(obj):
            xs.append(p.x)
            ys.append(p.y)
            zs.append(p.z)
    if not xs:
        return (0.0, 1.0, -1.0, 1.0, 0.0, 1.0)
    return min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)


def append_scene_objects(blend_path: Path) -> list[bpy.types.Object]:
    before = set(bpy.data.objects)
    with bpy.data.libraries.load(str(blend_path), link=False) as (data_from, data_to):
        data_to.objects = list(data_from.objects)
    new_objects = []
    for obj in bpy.data.objects:
        if obj in before:
            continue
        if obj.name not in bpy.context.scene.collection.objects:
            bpy.context.scene.collection.objects.link(obj)
        new_objects.append(obj)
    return new_objects


def transform_module(objects: list[bpy.types.Object], module_start_x: float, module_length: float, half_width: float) -> dict:
    min_x, max_x, min_y, max_y, min_z, _ = objects_bbox(objects)
    width_x = max(max_x - min_x, 1.0)
    width_y = max(max_y - min_y, 1.0)
    scale = min(module_length / width_x, (2.0 * half_width) / width_y, 1.0)
    center_y = (min_y + max_y) / 2.0
    for obj in objects:
        obj.location.x = module_start_x + (obj.location.x - min_x) * scale
        obj.location.y = (obj.location.y - center_y) * scale
        obj.location.z = (obj.location.z - min_z) * scale
        obj.scale *= scale
    return {"source_bbox": [min_x, max_x, min_y, max_y, min_z], "scale": scale}


def add_box_between(name: str, x0: float, x1: float, y: float, z: float, width: float, height: float, mat: bpy.types.Material) -> bpy.types.Object:
    length = max(x1 - x0, 0.1)
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=((x0 + x1) / 2.0, y, z))
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = (length, width, height)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(mat)
    obj["sionna_bsdf_id"] = str(mat.get("sionna_bsdf_id", "mat-vn_metal"))
    return obj


def add_visible_track(module_id: str, start_x: float, length: float, z_func, mats: dict) -> list[dict]:
    samples = []
    segment = 25.0
    sleeper_step = 50.0
    gauge = 1.435
    x = start_x
    idx = 0
    while x < start_x + length:
        x1 = min(x + segment, start_x + length)
        z0 = z_func((x + x1) / 2.0)
        add_box_between(f"VISIBLE_Rail_L_{module_id}_{idx:04d}", x, x1, gauge / 2.0, z0 + 0.34, 0.10, 0.18, mats["rail"])
        add_box_between(f"VISIBLE_Rail_R_{module_id}_{idx:04d}", x, x1, -gauge / 2.0, z0 + 0.34, 0.10, 0.18, mats["rail"])
        add_box_between(f"Track_Ballast_{module_id}_{idx:04d}", x, x1, 0.0, z0 + 0.08, 5.0, 0.16, mats["ballast"])
        if idx % max(1, int(sleeper_step / segment)) == 0:
            add_box_between(f"VISIBLE_Sleeper_{module_id}_{idx:04d}", x, x + 2.5, 0.0, z0 + 0.22, 2.8, 0.18, mats["sleeper"])
        samples.append({"x": round((x + x1) / 2.0, 3), "y": 0.0, "z": round(z0 + 4.2, 3)})
        x = x1
        idx += 1
    return samples


def add_centerline(samples: list[dict]) -> None:
    mesh = bpy.data.meshes.new("Composite_RT_Trajectory_Centerline_Mesh")
    verts = [(p["x"], p["y"], p["z"]) for p in samples]
    edges = [(i, i + 1) for i in range(len(verts) - 1)]
    mesh.from_pydata(verts, edges, [])
    mesh.update()
    obj = bpy.data.objects.new("RT_Trajectory_Centerline", mesh)
    bpy.context.scene.collection.objects.link(obj)


def read_hgt_gz(path: Path) -> tuple[list[int], int]:
    raw = gzip.decompress(path.read_bytes())
    count = len(raw) // 2
    size = int(math.sqrt(count))
    values = list(struct.unpack(f">{count}h", raw))
    return values, size


def bilinear_hgt(values: list[int], size: int, lat: float, lon: float) -> float:
    row = (17.0 - lat) * (size - 1)
    col = (lon - 108.0) * (size - 1)
    row = max(0.0, min(size - 1.001, row))
    col = max(0.0, min(size - 1.001, col))
    r0, c0 = int(row), int(col)
    dr, dc = row - r0, col - c0
    def val(r: int, c: int) -> float:
        v = values[r * size + c]
        return 0.0 if v <= -32768 else float(v)
    v00 = val(r0, c0)
    v10 = val(min(r0 + 1, size - 1), c0)
    v01 = val(r0, min(c0 + 1, size - 1))
    v11 = val(min(r0 + 1, size - 1), min(c0 + 1, size - 1))
    return (v00 * (1 - dr) * (1 - dc) + v10 * dr * (1 - dc) + v01 * (1 - dr) * dc + v11 * dr * dc)


def add_dem_terrain(module: dict, start_x: float, mats: dict, hgt_path: Path) -> dict:
    values, size = read_hgt_gz(hgt_path)
    south, west, north, east = module["dem_bbox"]
    nx, ny = 120, 48
    heights = []
    for ix in range(nx):
        lat = south + (north - south) * ix / (nx - 1)
        for iy in range(ny):
            lon = west + (east - west) * iy / (ny - 1)
            heights.append(bilinear_hgt(values, size, lat, lon))
    min_h = min(heights)
    verts = []
    faces = []
    idx = 0
    for ix in range(nx):
        x = start_x + module["length_m"] * ix / (nx - 1)
        for iy in range(ny):
            y = -module["half_width_m"] + 2.0 * module["half_width_m"] * iy / (ny - 1)
            z = max(0.0, heights[idx] - min_h)
            verts.append((x, y, z))
            idx += 1
    for ix in range(nx - 1):
        for iy in range(ny - 1):
            a = ix * ny + iy
            faces.append((a, a + 1, a + ny + 1, a + ny))
    mesh = bpy.data.meshes.new("HaiVan_SRTM_DEM_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new("HaiVan_SRTM_DEM_Terrain", mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.data.materials.append(mats["terrain"])
    obj["sionna_bsdf_id"] = "mat-vn_granite"
    return {"min_elevation_m": min_h, "max_elevation_m": max(heights), "grid": [nx, ny]}


def add_gnb(name: str, x: float, y: float, z_ground: float, mats: dict) -> dict:
    height = 30.0
    bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.35, depth=height, location=(x, y, z_ground + height / 2.0))
    mast = bpy.context.object
    mast.name = f"{name}_mast"
    mast.data.materials.append(mats["gnb"])
    mast["sionna_bsdf_id"] = "mat-vn_metal"
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x, y, z_ground + height))
    ant = bpy.context.object
    ant.name = f"{name}_antenna"
    ant.dimensions = (1.0, 0.35, 1.4)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    ant.data.materials.append(mats["gnb"])
    ant["sionna_bsdf_id"] = "mat-vn_metal"
    return {"name": name, "position_m": [round(x, 3), round(y, 3), round(z_ground + height, 3)]}


def add_module_labels(module: dict, start_x: float, mats: dict) -> None:
    bpy.ops.object.text_add(location=(start_x + 80.0, -module["half_width_m"] + 40.0, 12.0), rotation=(math.radians(75), 0.0, 0.0))
    obj = bpy.context.object
    obj.name = f"ZONE_LABEL_{module['id']}"
    obj.data.body = module["label"]
    obj.data.size = 45.0
    obj.data.align_x = "LEFT"
    obj.data.align_y = "CENTER"
    obj.data.materials.append(mats["label"])


def main() -> None:
    args = parse_args()
    scene_dir = Path(args.scene_dir)
    out = Path(args.out)
    report_path = Path(args.report)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = 1.0

    mats = {
        "rail": make_material("VISIBLE_Rail_Red_Metal", (1.0, 0.05, 0.02, 1.0), "mat-vn_metal"),
        "ballast": make_material("Visible_Ballast_Dark", (0.16, 0.16, 0.16, 1.0), "mat-vn_concrete"),
        "sleeper": make_material("Visible_Sleeper_Yellow", (1.0, 0.78, 0.05, 1.0), "mat-vn_concrete"),
        "gnb": make_material("GNB_Blue_Metal", (0.05, 0.25, 1.0, 1.0), "mat-vn_metal"),
        "terrain": make_material("HaiVan_DEM_Granite", (0.32, 0.36, 0.31, 1.0), "mat-vn_granite"),
        "label": make_material("Zone_Label_White", (1.0, 1.0, 1.0, 1.0), "mat-vn_concrete"),
    }

    module_reports = []
    all_samples = []
    gnb_reports = []
    x_cursor = 0.0
    gnb_index = 1
    for module in MODULES:
        blend_path = scene_dir / f"{module['id']}.blend"
        objects = append_scene_objects(blend_path)
        transform_report = transform_module(objects, x_cursor, module["length_m"], module["half_width_m"])

        terrain_report = None
        if "dem_bbox" in module:
            terrain_report = add_dem_terrain(module, x_cursor, mats, Path(args.dem_hgt_gz))

        def z_func(x: float, mod=module, start=x_cursor) -> float:
            if "dem_bbox" not in mod:
                return 0.0
            # Use a smoothed synthetic track elevation sampled from the DEM corridor trend.
            t = (x - start) / max(mod["length_m"], 1.0)
            return 15.0 + 55.0 * math.sin(math.pi * t) ** 2 + 20.0 * math.sin(4.0 * math.pi * t)

        module_samples = add_visible_track(module["id"], x_cursor, module["length_m"], z_func, mats)
        all_samples.extend(module_samples)
        add_module_labels(module, x_cursor, mats)

        # Practical 5G/FRMCS-style trackside planning: denser in urban/mountain, sparser in open lagoon/delta.
        n_gnbs = max(2, int(math.ceil(module["length_m"] / module["gnb_spacing_m"])) + 1)
        for i in range(n_gnbs):
            ratio = i / max(n_gnbs - 1, 1)
            x = x_cursor + 120.0 + ratio * max(module["length_m"] - 240.0, 1.0)
            y = module["gnb_offset_m"] * (1.0 if i % 2 else -1.0)
            gnb_reports.append(add_gnb(f"GNB_{gnb_index:02d}_{module['id']}", x, y, z_func(x), mats))
            gnb_index += 1

        module_reports.append(
            {
                "id": module["id"],
                "label": module["label"],
                "start_x_m": x_cursor,
                "end_x_m": x_cursor + module["length_m"],
                "length_m": module["length_m"],
                "half_width_m": module["half_width_m"],
                "source_blend": str(blend_path.resolve()),
                "transform": transform_report,
                "terrain": terrain_report,
            }
        )
        x_cursor += module["length_m"]

    add_centerline(all_samples)
    apply_rt_tags()

    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out))

    report = {
        "out": str(out.resolve()),
        "total_length_m": x_cursor,
        "module_count": len(MODULES),
        "gnb_count": len(gnb_reports),
        "trajectory_samples": len(all_samples),
        "modules": module_reports,
        "base_stations": gnb_reports,
        "design_note": "Composite representative Vietnam railway propagation corridor. Modules are placed contiguously for controlled ray-tracing comparison; coordinates are not real geographic distances.",
        "rail_visibility": "Synthetic red/yellow VISIBLE_Rail_* objects and RT_Trajectory_Centerline were added so the route is immediately visible when opening the blend.",
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    report_path.with_suffix(".md").write_text(
        "\n".join(
            [
                "# Vietnam Composite Railway RT Corridor",
                "",
                f"- Blend: `{out.resolve()}`",
                f"- Total length: {x_cursor/1000.0:.3f} km",
                f"- Modules: {len(MODULES)}",
                f"- gNB count: {len(gnb_reports)}",
                f"- Trajectory samples: {len(all_samples)}",
                "- DEM: SRTM N16E108 added for Hai Van module.",
                "- Visible track: red rail + yellow sleepers, with `RT_Trajectory_Centerline`.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
