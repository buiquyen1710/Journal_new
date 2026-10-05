from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1 :] if "--" in argv else argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args(argv)


def bbox(obj: bpy.types.Object) -> dict:
    pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    xs, ys, zs = [p.x for p in pts], [p.y for p in pts], [p.z for p in pts]
    return {
        "min": [min(xs), min(ys), min(zs)],
        "max": [max(xs), max(ys), max(zs)],
        "dims": [max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)],
    }


def evaluated_mesh_stats(obj: bpy.types.Object) -> dict:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(depsgraph)
    mesh = ev.to_mesh()
    try:
        mesh.calc_loop_triangles()
        return {
            "vertices": len(mesh.vertices),
            "polygons": len(mesh.polygons),
            "triangles": len(mesh.loop_triangles),
            "bbox": bbox(obj),
        }
    finally:
        ev.to_mesh_clear()


def main() -> None:
    args = parse_args()
    bpy.ops.wm.open_mainfile(filepath=str(Path(args.blend).resolve()))
    objects = {obj.name: obj for obj in bpy.context.scene.objects if obj.type == "MESH"}
    report = {"objects": {}, "intersection_notes": []}
    for name in ("Mountain_Granite", "Railway", "Train", "Concrete_Bridge"):
        obj = objects.get(name)
        if obj:
            report["objects"][name] = evaluated_mesh_stats(obj)

    mountain = objects.get("Mountain_Granite")
    railway = objects.get("Railway")
    if mountain and railway:
        mb = bbox(mountain)
        rb = bbox(railway)
        overlap = not (
            rb["max"][0] < mb["min"][0]
            or rb["min"][0] > mb["max"][0]
            or rb["max"][1] < mb["min"][1]
            or rb["min"][1] > mb["max"][1]
            or rb["max"][2] < mb["min"][2]
            or rb["min"][2] > mb["max"][2]
        )
        report["mountain_railway_bbox_overlap"] = overlap
        report["intersection_notes"].append(
            "Bounding-box overlap only proves the rail passes through/near the mountain volume; it does not prove the mountain mesh has tunnel interior faces."
        )

    tunnel_like = []
    for obj in objects.values():
        text = " ".join(
            part.lower()
            for part in (
                obj.name,
                obj.data.name if obj.data else "",
                obj.active_material.name if obj.active_material else "",
            )
        )
        if any(key in text for key in ("tunnel", "portal", "cave", "shaft", "inside", "wall")):
            tunnel_like.append(obj.name)
    report["tunnel_named_objects"] = tunnel_like
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
