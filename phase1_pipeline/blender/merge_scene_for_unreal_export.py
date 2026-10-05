from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import bpy
from mathutils import Matrix


GEOMETRY_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT"}
MARKER_NAME_RE = re.compile(r"(gnb|tx|rx|ue|receiver|transmitter|train|rail)", re.IGNORECASE)


def args_after_double_dash():
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def unhide_everything():
    for collection in bpy.data.collections:
        collection.hide_viewport = False
        collection.hide_render = False

    for obj in bpy.data.objects:
        obj.hide_set(False)
        obj.hide_viewport = False
        obj.hide_render = False


def safe_scene_name(scene_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", scene_id).strip("_")


def object_world_position(obj):
    return obj.matrix_world.translation.copy()


def add_marker_cube_for_empty(empty_obj, size=4.0):
    """Represent useful non-mesh marker empties as small cubes before joining."""
    location = object_world_position(empty_obj)
    bpy.ops.mesh.primitive_cube_add(size=size, location=location)
    cube = bpy.context.object
    cube.name = f"marker_{empty_obj.name}"
    cube.data.name = f"{cube.name}_mesh"
    cube.rotation_euler = empty_obj.rotation_euler
    cube.scale = empty_obj.scale
    return cube


def convert_selected_geometry_to_mesh(objects):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    if objects:
        bpy.context.view_layer.objects.active = objects[0]
        bpy.ops.object.convert(target="MESH")
    return [obj for obj in bpy.context.selected_objects if obj.type == "MESH"]


def transform_mesh_to_world(obj):
    """Bake object transform into mesh data, then reset object transform to identity."""
    if obj.data.users > 1:
        obj.data = obj.data.copy()
    mesh = obj.data
    mesh.transform(obj.matrix_world)
    mesh.update()
    obj.matrix_world = Matrix.Identity(4)


def join_meshes_to_single_object(scene_id: str):
    unhide_everything()

    marker_cubes = []
    for obj in list(bpy.data.objects):
        if obj.type == "EMPTY" and MARKER_NAME_RE.search(obj.name):
            marker_cubes.append(add_marker_cube_for_empty(obj))

    geometry_objects = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type in GEOMETRY_TYPES and obj.visible_get()
    ]
    converted_meshes = convert_selected_geometry_to_mesh(geometry_objects)

    mesh_objects = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and obj.visible_get()
    ]

    if not mesh_objects:
        raise RuntimeError(f"{scene_id}: no mesh objects available to merge")

    # Bake transforms first so the final mesh has identity transform and imports cleanly in UE.
    for obj in mesh_objects:
        transform_mesh_to_world(obj)

    merged_name = f"{safe_scene_name(scene_id)}__UE_SINGLE_MESH"
    bpy.ops.mesh.primitive_cube_add(size=0.01, location=(0.0, 0.0, 0.0))
    merged = bpy.context.object
    merged.name = merged_name
    merged.data.name = f"{merged_name}_mesh"
    # Remove the placeholder cube geometry but keep a valid mesh object as join target.
    merged.data.clear_geometry()

    bpy.ops.object.select_all(action="DESELECT")
    merged.select_set(True)
    for obj in mesh_objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = merged
    bpy.ops.object.join()

    merged = bpy.context.object
    merged.name = merged_name
    merged.data.name = f"{merged_name}_mesh"
    merged.location = (0.0, 0.0, 0.0)
    merged.rotation_euler = (0.0, 0.0, 0.0)
    merged.scale = (1.0, 1.0, 1.0)

    # Keep the copy intentionally simple: one mesh object only.
    for obj in list(bpy.data.objects):
        if obj != merged:
            bpy.data.objects.remove(obj, do_unlink=True)

    for collection in list(bpy.data.collections):
        if not collection.objects and not collection.children:
            bpy.data.collections.remove(collection)

    return {
        "merged_object": merged.name,
        "source_geometry_objects": len(geometry_objects),
        "mesh_objects_joined": len(mesh_objects),
        "marker_cubes_created": len(marker_cubes),
        "vertices": len(merged.data.vertices),
        "edges": len(merged.data.edges),
        "polygons": len(merged.data.polygons),
        "material_slots": len(merged.material_slots),
        "final_object_count": len(bpy.data.objects),
    }


def export_selected_merged_fbx(fbx_path: Path, merged_name: str):
    merged = bpy.data.objects[merged_name]
    bpy.ops.object.select_all(action="DESELECT")
    merged.select_set(True)
    bpy.context.view_layer.objects.active = merged
    fbx_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.fbx(
        filepath=str(fbx_path),
        use_selection=True,
        global_scale=1.0,
        apply_unit_scale=True,
        bake_space_transform=False,
        object_types={"MESH"},
        mesh_smooth_type="OFF",
        use_mesh_modifiers=True,
        add_leaf_bones=False,
        path_mode="AUTO",
    )


def main():
    args = args_after_double_dash()
    if len(args) != 1:
        raise SystemExit("Usage: blender --background --python merge_scene_for_unreal_export.py -- <scene_export_manifest.json>")

    manifest_path = Path(args[0])
    out_root = manifest_path.parent
    blend_out_dir = out_root / "unreal_merged_blends"
    fbx_out_dir = out_root / "unreal_merged_fbx"
    blend_out_dir.mkdir(parents=True, exist_ok=True)
    fbx_out_dir.mkdir(parents=True, exist_ok=True)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    jobs = manifest.get("export_jobs", [])

    results = []
    for job in jobs:
        scene_id = job["scene_id"]
        source_blend = Path(job["blend"])
        copy_blend = blend_out_dir / f"{scene_id}_UE_single_mesh.blend"
        fbx_path = fbx_out_dir / f"{scene_id}_UE_single_mesh.fbx"

        if not source_blend.exists():
            results.append(
                {
                    "scene_id": scene_id,
                    "status": "missing_blend",
                    "source_blend": str(source_blend),
                    "merged_blend": str(copy_blend),
                    "fbx": str(fbx_path),
                }
            )
            print(f"[SKIP] {scene_id}: missing {source_blend}")
            continue

        print(f"[OPEN] {scene_id}: {source_blend}")
        bpy.ops.wm.open_mainfile(filepath=str(source_blend))
        stats = join_meshes_to_single_object(scene_id)

        print(f"[SAVE] {scene_id}: {copy_blend}")
        bpy.ops.wm.save_as_mainfile(filepath=str(copy_blend))

        print(f"[FBX] {scene_id}: {fbx_path}")
        export_selected_merged_fbx(fbx_path, stats["merged_object"])

        results.append(
            {
                "scene_id": scene_id,
                "status": "merged_and_exported",
                "source_blend": str(source_blend),
                "merged_blend": str(copy_blend),
                "fbx": str(fbx_path),
                "merged_blend_bytes": copy_blend.stat().st_size if copy_blend.exists() else 0,
                "fbx_bytes": fbx_path.stat().st_size if fbx_path.exists() else 0,
                **stats,
            }
        )

    result_path = out_root / "unreal_single_mesh_export_results.json"
    result_path.write_text(json.dumps({"results": results}, indent=2), encoding="utf-8")
    print(f"[DONE] wrote {result_path}")


if __name__ == "__main__":
    main()
