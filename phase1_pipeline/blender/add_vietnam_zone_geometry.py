from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1 :] if "--" in argv else argv[1:]
    parser = argparse.ArgumentParser(description="Add Vietnam terrain zone geometry for Sionna RT.")
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--report", required=True)
    return parser.parse_args(argv)


def mat(name: str, color, bsdf_id: str, metallic: float = 0.0) -> bpy.types.Material:
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    node = m.node_tree.nodes.get("Principled BSDF")
    if node:
        node.inputs["Base Color"].default_value = color
        node.inputs["Metallic"].default_value = metallic
        node.inputs["Roughness"].default_value = 0.42
    m["sionna_bsdf_id"] = bsdf_id
    return m


def assign(obj: bpy.types.Object, material: bpy.types.Material, bsdf_id: str) -> None:
    obj.data.materials.clear()
    obj.data.materials.append(material)
    obj["sionna_bsdf_id"] = bsdf_id


def ensure_collection(name: str) -> bpy.types.Collection:
    old = bpy.data.collections.get(name)
    if old:
        for obj in list(old.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        return old
    col = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(col)
    return col


def link_to(obj: bpy.types.Object, col: bpy.types.Collection) -> None:
    for existing in list(obj.users_collection):
        existing.objects.unlink(obj)
    col.objects.link(obj)


def railway_bounds() -> tuple[float, float, float, float]:
    rail = bpy.data.objects.get("Railway")
    if rail is None:
        raise RuntimeError("Railway object not found.")
    pts = [rail.matrix_world @ Vector(c) for c in rail.bound_box]
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    return min(xs), max(xs), min(ys), max(ys)


class LoopPath:
    def __init__(self, bounds: tuple[float, float, float, float], z: float = 1.2):
        min_x, max_x, min_y, max_y = bounds
        self.points = [
            Vector((min_x, min_y, z)),
            Vector((max_x, min_y, z)),
            Vector((max_x, max_y, z)),
            Vector((min_x, max_y, z)),
            Vector((min_x, min_y, z)),
        ]
        self.lengths = [(b - a).length for a, b in zip(self.points, self.points[1:])]
        self.total = sum(self.lengths)

    def sample(self, s: float) -> tuple[Vector, Vector, Vector]:
        s = max(0.0, min(float(s), self.total))
        elapsed = 0.0
        for a, b, length in zip(self.points, self.points[1:], self.lengths):
            if s <= elapsed + length or b == self.points[-1]:
                t = 0.0 if length <= 1e-9 else (s - elapsed) / length
                pos = a.lerp(b, max(0.0, min(1.0, t)))
                tangent = (b - a).normalized()
                normal = Vector((-tangent.y, tangent.x, 0.0))
                return pos, tangent, normal
            elapsed += length
        tangent = (self.points[-1] - self.points[-2]).normalized()
        return self.points[-1], tangent, Vector((-tangent.y, tangent.x, 0.0))


def add_box(name: str, location: Vector, dims: tuple[float, float, float], yaw: float, material, bsdf: str, col) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location, rotation=(0.0, 0.0, yaw))
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dims
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    assign(obj, material, bsdf)
    link_to(obj, col)
    return obj


def add_cylinder(name: str, location: Vector, radius: float, depth: float, material, bsdf: str, col, vertices: int = 16) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=depth, vertices=vertices, location=location)
    obj = bpy.context.object
    obj.name = name
    assign(obj, material, bsdf)
    link_to(obj, col)
    return obj


def yaw_from_tangent(tangent: Vector) -> float:
    return math.atan2(tangent.y, tangent.x)


def add_zone_marker(path: LoopPath, s0: float, s1: float, name: str, col, material, bsdf: str) -> None:
    mid, tangent, _ = path.sample((s0 + s1) / 2.0)
    add_box(name, Vector((mid.x, mid.y, 0.03)), (s1 - s0, 1.0, 0.06), yaw_from_tangent(tangent), material, bsdf, col)


def add_wet_fields(path: LoopPath, col, material) -> int:
    count = 0
    for s0, s1 in ((0, 375), (375, 750)):
        mid, tangent, normal = path.sample((s0 + s1) / 2)
        for side in (-1, 1):
            loc = mid + normal * side * 115
            add_box(f"VN_A_WetRiceField_{count:02d}", Vector((loc.x, loc.y, 0.0)), (s1 - s0, 180, 0.05), yaw_from_tangent(tangent), material, "mat-vn_wet_ground", col)
            count += 1
    return count


def add_palms(path: LoopPath, col, veg_mat) -> int:
    count = 0
    for s in range(25, 750, 25):
        pos, _, normal = path.sample(s)
        for side in (-1, 1):
            base = pos + normal * side * 22
            trunk = add_cylinder(f"VN_A_Palm_Trunk_{count:03d}", Vector((base.x, base.y, 7.5)), 0.18, 15.0, veg_mat, "mat-vn_vegetation", col, 12)
            crown = add_cylinder(f"VN_A_Palm_Crown_{count:03d}", Vector((base.x, base.y, 14.5)), 1.6, 2.2, veg_mat, "mat-vn_vegetation", col, 12)
            count += 1
    return count


def add_power_poles(path: LoopPath, col, concrete_mat) -> int:
    count = 0
    for s in range(15, 750, 30):
        pos, _, normal = path.sample(s)
        base = pos + normal * 14
        add_cylinder(f"VN_A_PowerPole_{count:03d}", Vector((base.x, base.y, 4.5)), 0.09, 9.0, concrete_mat, "mat-vn_concrete", col, 12)
        count += 1
    return count


def add_rural_houses(path: LoopPath, col, wall_mat, metal_mat) -> int:
    count = 0
    for idx, s in enumerate((850, 1000, 1150, 1300, 1425)):
        pos, tangent, normal = path.sample(s)
        yaw = yaw_from_tangent(tangent)
        for j, offset in enumerate((-18, 0, 18)):
            side = -1 if idx % 2 else 1
            center = pos + tangent * offset + normal * side * (62 + 7 * j)
            add_box(f"VN_B_RuralHouse_Wall_{idx}_{j}", Vector((center.x, center.y, 2.0)), (8, 10, 4), yaw, wall_mat, "mat-vn_concrete", col)
            add_box(f"VN_B_MetalRoof_{idx}_{j}", Vector((center.x, center.y, 5.0)), (10, 12, 0.35), yaw, metal_mat, "mat-vn_metal", col)
            count += 2
    return count


def add_orchard_and_bamboo(path: LoopPath, col, veg_mat) -> int:
    count = 0
    for s in range(900, 1125, 25):
        pos, _, normal = path.sample(s)
        for side in (-1, 1):
            base = pos + normal * side * 38
            add_cylinder(f"VN_B_OrchardTree_{count:03d}", Vector((base.x, base.y, 6.0)), 2.5, 12.0, veg_mat, "mat-vn_vegetation", col, 12)
            count += 1
    for s in (980, 1210, 1380):
        pos, tangent, normal = path.sample(s)
        center = pos + normal * -24
        add_box(f"VN_B_TreBelt_{count:03d}", Vector((center.x, center.y, 6.0)), (50, 10, 12), yaw_from_tangent(tangent), veg_mat, "mat-vn_vegetation", col)
        count += 1
    return count


def add_canals(path: LoopPath, col, water_mat) -> int:
    count = 0
    for s in (820, 1000, 1180, 1360):
        pos, tangent, normal = path.sample(s)
        yaw = yaw_from_tangent(normal)
        add_box(f"VN_B_IrrigationCanal_{count}", Vector((pos.x, pos.y, -0.05)), (160, 8, 0.1), yaw, water_mat, "mat-vn_wet_ground", col)
        count += 1
    return count


def add_tunnel_segment(path: LoopPath, s0: float, s1: float, col, concrete_mat, granite_mat) -> int:
    count = 0
    step = 25.0
    s = s0
    while s < s1 - 1e-6:
        e = min(s + step, s1)
        mid, tangent, normal = path.sample((s + e) / 2)
        yaw = yaw_from_tangent(tangent)
        seg_len = e - s
        # Tunnel interior: 11 m wide, 8 m high with thick shell faces
        add_box(f"VN_C_TunnelFloor_{count:03d}", Vector((mid.x, mid.y, 0.0)), (seg_len, 11.5, 0.45), yaw, concrete_mat, "mat-vn_concrete", col)
        add_box(f"VN_C_TunnelCeiling_{count:03d}", Vector((mid.x, mid.y, 8.0)), (seg_len, 11.5, 0.45), yaw, concrete_mat, "mat-vn_concrete", col)
        left = mid + normal * 5.75
        right = mid - normal * 5.75
        add_box(f"VN_C_TunnelWall_Left_{count:03d}", Vector((left.x, left.y, 4.0)), (seg_len, 0.45, 8.0), yaw, concrete_mat, "mat-vn_concrete", col)
        add_box(f"VN_C_TunnelWall_Right_{count:03d}", Vector((right.x, right.y, 4.0)), (seg_len, 0.45, 8.0), yaw, concrete_mat, "mat-vn_concrete", col)
        count += 1
        s = e
    for name, s in (("Entry", s0), ("Exit", s1)):
        pos, tangent, normal = path.sample(s)
        yaw = yaw_from_tangent(tangent)
        add_box(f"VN_C_Portal_{name}", Vector((pos.x, pos.y, 4.2)), (2.0, 15.0, 8.4), yaw, concrete_mat, "mat-vn_concrete", col)
    for s in (s0 - 70, s0 - 35, s1 + 35, s1 + 70):
        pos, tangent, normal = path.sample(s)
        for side in (-1, 1):
            center = pos + normal * side * 42
            add_box(f"VN_C_RockFace_{count:03d}_{side}", Vector((center.x, center.y, 50.0)), (80.0, 4.0, 100.0), yaw_from_tangent(tangent), granite_mat, "mat-vn_granite", col)
            count += 1
    return count


def add_zone_c_forest_and_talus(path: LoopPath, col, veg_mat, granite_mat) -> int:
    count = 0
    for s in range(1450, 2051, 50):
        pos, _, normal = path.sample(s)
        for side in (-1, 1):
            forest = pos + normal * side * 82
            add_cylinder(f"VN_C_MontaneForest_{count:03d}", Vector((forest.x, forest.y, 9.0)), 3.0, 18.0, veg_mat, "mat-vn_vegetation", col, 12)
            talus = pos + normal * side * 15
            add_box(f"VN_C_TalusScree_{count:03d}", Vector((talus.x, talus.y, 1.4)), (22.0, 8.0, 2.8), 0.0, granite_mat, "mat-vn_granite", col)
            count += 1
    return count


def add_zone_d(path: LoopPath, col, laterite_mat, water_mat, veg_mat, concrete_mat) -> int:
    count = 0
    for s0, s1 in ((2050, 2500), (2500, 3000)):
        mid, tangent, normal = path.sample((s0 + s1) / 2)
        yaw = yaw_from_tangent(tangent)
        for side in (-1, 1):
            center = mid + normal * side * 72
            add_box(f"VN_D_FoothillSlope_{count:03d}_{side}", Vector((center.x, center.y, 18.0)), (s1 - s0, 70.0, 36.0), yaw, laterite_mat, "mat-vn_laterite", col)
            count += 1
    for s in (2200, 2600):
        pos, tangent, normal = path.sample(s)
        add_box(f"VN_D_MountainStream_{count:03d}", Vector((pos.x, pos.y, -0.02)), (180, 24, 0.08), yaw_from_tangent(normal), water_mat, "mat-vn_wet_ground", col)
        count += 1
    for s in range(2150, 2950, 80):
        pos, _, normal = path.sample(s)
        side = 1 if count % 2 else -1
        loc = pos + normal * side * 95
        add_cylinder(f"VN_D_SecondaryForest_{count:03d}", Vector((loc.x, loc.y, 6.0)), 3.0, 12.0, veg_mat, "mat-vn_vegetation", col, 12)
        count += 1
    pos, tangent, normal = path.sample(2850)
    center = pos + normal * 55
    add_box("VN_D_SmallStation", Vector((center.x, center.y, 4.0)), (60, 15, 8), yaw_from_tangent(tangent), concrete_mat, "mat-vn_concrete", col)
    return count + 1


def write_report(path: Path, payload: dict) -> None:
    lines = [
        "# Vietnam Zone Geometry Report",
        "",
        f"- Source blend: `{payload['source']}`",
        f"- Output blend: `{payload['output']}`",
        f"- Loop length used for zone mapping: {payload['loop_length_m']:.3f} m",
        "",
        "## Zone Mapping",
        "",
    ]
    for zone in payload["zones"]:
        lines.append(f"- {zone['name']}: s={zone['s0_m']:.1f}-{zone['s1_m']:.1f} m; objects added={zone['objects_added']}")
    lines.extend(["", "## Notes", ""])
    lines.append("- Zone C now has explicit tunnel floor, ceiling, left/right walls, portals, rock faces, forest, and talus scree.")
    lines.append("- Object names avoid heavy original asset keywords where needed; new geometry is low-poly and Sionna-friendly.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    bpy.ops.wm.open_mainfile(filepath=str(Path(args.source).resolve()))
    bounds = railway_bounds()
    path = LoopPath(bounds, z=1.2)
    col = ensure_collection("VN_Zone_Geometry")

    concrete = mat("VN_RT_Concrete", (0.55, 0.55, 0.52, 1), "mat-vn_concrete")
    granite = mat("VN_RT_Granite", (0.42, 0.43, 0.45, 1), "mat-vn_granite")
    vegetation = mat("VN_RT_Vegetation", (0.18, 0.38, 0.16, 1), "mat-vn_vegetation")
    water = mat("VN_RT_WaterWetGround", (0.12, 0.26, 0.32, 1), "mat-vn_wet_ground")
    metal = mat("VN_RT_MetalRoof", (0.60, 0.62, 0.64, 1), "mat-vn_metal", metallic=1.0)
    wall = mat("VN_RT_BrickWall", (0.56, 0.33, 0.25, 1), "mat-vn_concrete")
    laterite = mat("VN_RT_Laterite", (0.55, 0.20, 0.10, 1), "mat-vn_laterite")
    marker = mat("VN_RT_ZoneMarker", (0.8, 0.8, 0.1, 1), "mat-vn_concrete")

    report = {
        "source": str(Path(args.source).resolve()),
        "output": str(Path(args.out).resolve()),
        "loop_length_m": path.total,
        "bounds": list(bounds),
        "zones": [],
    }
    for s0, s1, name in ((0, 750, "Zone_A_Viaduct_DongBang"), (750, 1500, "Zone_B_Ground_LangMac"), (1500, 2000, "Zone_C_Tunnel_TruongSon"), (2000, 3000, "Zone_D_Portal_ThungLung")):
        add_zone_marker(path, s0, s1, f"VN_{name}_Marker", col, marker, "mat-vn_concrete")

    a_count = add_wet_fields(path, col, water) + add_palms(path, col, vegetation) + add_power_poles(path, col, concrete)
    b_count = add_rural_houses(path, col, wall, metal) + add_orchard_and_bamboo(path, col, vegetation) + add_canals(path, col, water)
    c_count = add_tunnel_segment(path, 1500, 2000, col, concrete, granite) + add_zone_c_forest_and_talus(path, col, vegetation, granite)
    d_count = add_zone_d(path, col, laterite, water, vegetation, concrete)
    for name, s0, s1, count in (
        ("Zone A - Viaduct/Wet Rice Field", 0, 750, a_count),
        ("Zone B - Rural Village", 750, 1500, b_count),
        ("Zone C - Truong Son Tunnel", 1500, 2000, c_count),
        ("Zone D - Portal/Foothills", 2000, 3000, d_count),
    ):
        report["zones"].append({"name": name, "s0_m": s0, "s1_m": s1, "objects_added": count})

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out))
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_report(report_path, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
