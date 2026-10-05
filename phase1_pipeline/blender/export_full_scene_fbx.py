from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy


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


def export_fbx(blend_path: Path, fbx_path: Path):
    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    unhide_everything()
    fbx_path.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.fbx(
        filepath=str(fbx_path),
        use_selection=False,
        global_scale=1.0,
        apply_unit_scale=True,
        bake_space_transform=False,
        object_types={"EMPTY", "CAMERA", "LIGHT", "MESH", "OTHER"},
        mesh_smooth_type="OFF",
        use_mesh_modifiers=True,
        add_leaf_bones=False,
        path_mode="AUTO",
    )


def main():
    args = args_after_double_dash()
    if len(args) != 1:
        raise SystemExit("Usage: blender --background --python export_full_scene_fbx.py -- <scene_export_manifest.json>")

    manifest_path = Path(args[0])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    jobs = manifest.get("export_jobs", [])

    results = []
    for job in jobs:
        scene_id = job["scene_id"]
        blend = Path(job["blend"])
        fbx = Path(job["fbx"])
        if not blend.exists():
            results.append({"scene_id": scene_id, "status": "missing_blend", "blend": str(blend), "fbx": str(fbx)})
            print(f"[SKIP] {scene_id}: missing blend {blend}")
            continue

        print(f"[EXPORT] {scene_id}: {blend} -> {fbx}")
        export_fbx(blend, fbx)
        results.append(
            {
                "scene_id": scene_id,
                "status": "exported",
                "blend": str(blend),
                "fbx": str(fbx),
                "fbx_bytes": fbx.stat().st_size if fbx.exists() else 0,
            }
        )

    result_path = manifest_path.parent / "fbx_export_results.json"
    result_path.write_text(json.dumps({"results": results}, indent=2), encoding="utf-8")
    print(f"[DONE] wrote {result_path}")


if __name__ == "__main__":
    main()
