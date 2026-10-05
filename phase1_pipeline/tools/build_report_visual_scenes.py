from __future__ import annotations

import argparse
import gzip
import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


PIPELINE = Path(__file__).resolve().parents[1]
ROOT = PIPELINE.parent
BLENDER = Path("D:/blender.exe")
MANIFEST = PIPELINE / "vietnam_railway_osm_scenes" / "scene_manifest.json"
OSM_DIR = PIPELINE / "osm_scene_sources"
REPORT_ROOT = PIPELINE / "report_visual_sionna_scenes"


SCENES = {
    "haiphong": "do_thi_cang_bien_HaiPhong-ThuongLy",
    "langco": "dam_pha_ven_bien_LangCo-HaiVanBac",
    "haivan": "deo_nui_ven_bien_HaiVanBac-HaiVanNam",
    "haiduong": "dong_bang_cong_nghiep_HaiDuong-PhuThai",
}


def run(cmd: list[str], log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        completed = subprocess.run(cmd, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
    if completed.returncode != 0:
        raise RuntimeError(f"Command failed ({completed.returncode}); see {log_path}")


def load_manifest() -> dict[str, dict]:
    rows = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {row["id"]: row for row in rows}


def base_station_yaml(count: int) -> str:
    blocks = []
    for idx in range(count):
        name = f"GNB_{chr(65 + idx)}"
        out = f"mpc_gnb_{chr(97 + idx)}"
        blocks.append(
            f"  - name: {name}\n"
            f"    output_name: {out}\n"
            f"    position_m: [0.0, 0.0, 30.0]\n"
            f"    facing: y-\n"
            f"    height_m: 30.0\n"
            f"    mast_radius_m: 0.22\n"
            f"    antenna_size_m: [0.9, 0.28, 1.35]\n"
            f"    ray_origin_clearance_m: 0.35"
        )
    return "\n".join(blocks)


def write_config(scene: dict) -> Path:
    output_dir = f"report_visual_sionna_scenes/{scene['id']}"
    station_count = 14 if scene["terrain_type"] == "deo_nui_ven_bien" else 6
    config_path = PIPELINE / "config" / f"config_{scene['id']}_report_visual.yaml"
    config_path.write_text(
        f"""scenario:
  type: external_loop_3000m
  name: {scene['id']}_report_visual

external_scene:
  source_blend: {scene['blend_file'].replace(chr(92), "/")}
  trajectory_spacing_m: 25.0
  read_gnb_positions_from_scene: true

export:
  max_obj_file_bytes: 120000000
  skip_curve_objects: true
  keep_curve_keywords: [RT_Rail]
  skip_object_keywords: [RT_Sleeper, RT_Trajectory_Centerline]
  corridor_clip_margin_m: 0.0
  skip_object_area_below_m2: 0.0

scene:
  length_m: 0.0
  width_m: 0.0

base_stations:
{base_station_yaml(station_count)}

train:
  receiver_height_m: 4.2
  lateral_offset_m: 0.0
  length_m: 25.0
  width_m: 3.4
  body_height_m: 4.3

simulation:
  frequency_hz: 30000000000.0
  train_speed_kmh: 350.0
  timestep_s: 0.001
  scene_margin_m: 0.0
  duration_s:

ray_tracing:
  max_depth: 6
  max_num_paths: 3000
  samples_per_src: 1600
  include_train_in_rt_scene: false
  enable_refraction: true
  enable_diffuse_reflection: true
  enable_diffraction: true
  enable_edge_diffraction: true
  enable_diffraction_lit_region: false
  synthetic_array: true
  min_relative_path_gain_db: 110.0
  max_paths_after_filter: 256
  require_sionna_backend: true
  fallback_on_empty_sionna_paths: false
  skip_snapshot_visualizations: true
  skip_station_validation_plots: true

paths:
  blend_file: {output_dir}/Train_{scene['id']}_report_visual.blend
  mitsuba_xml: {output_dir}/scene.xml
  mesh_dir: {output_dir}/meshes
  trace_csv: {output_dir}/ns3_trace.csv
  trace_csv_pattern: {output_dir}/{{station}}.csv
  trace_manifest: {output_dir}/trace_manifest.json
  doppler_plot: {output_dir}/doppler_vs_time.png
  doppler_plot_pattern: {output_dir}/{{station}}_doppler_vs_time.png
  path_count_plot: {output_dir}/path_count_vs_time.png
  path_count_plot_pattern: {output_dir}/{{station}}_path_count_vs_time.png
  scene_metadata: {output_dir}/scene_metadata.json
""",
        encoding="utf-8",
    )
    return config_path


def add_colors_to_xml(xml_path: Path) -> None:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    colors = {
        "mat-vn_concrete": "0.78,0.78,0.73",
        "mat-vn_concrete_rough": "0.55,0.55,0.52",
        "mat-vn_metal": "0.16,0.16,0.18",
        "mat-vn_glass": "0.45,0.64,0.85",
        "mat-vn_granite": "0.30,0.30,0.28",
        "mat-vn_vegetation": "0.14,0.42,0.18",
        "mat-vn_wet_ground": "0.04,0.38,0.95",
        "mat-vn_laterite": "0.42,0.35,0.25",
    }
    for bsdf in root.findall("bsdf"):
        bsdf_id = bsdf.attrib.get("id", "")
        if bsdf_id not in colors:
            continue
        for child in list(bsdf):
            if child.tag == "rgb" and child.attrib.get("name") == "color":
                bsdf.remove(child)
        ET.SubElement(bsdf, "rgb", {"name": "color", "value": colors[bsdf_id]})
    ET.indent(tree, space="  ")
    tree.write(xml_path, encoding="utf-8", xml_declaration=True)


def gunzip_dem() -> Path | None:
    gz = PIPELINE / "dem" / "N16E108.hgt.gz"
    if not gz.exists():
        return None
    hgt = PIPELINE / "dem" / "N16E108.hgt"
    if not hgt.exists():
        with gzip.open(gz, "rb") as src, hgt.open("wb") as dst:
            shutil.copyfileobj(src, dst)
    return hgt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", action="append", choices=sorted(SCENES), help="Scene alias; repeatable.")
    parser.add_argument("--skip-dem", action="store_true")
    args = parser.parse_args()

    selected = args.scene or ["haiphong", "langco", "haivan"]
    manifest = load_manifest()
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    summary = []

    for alias in selected:
        scene = manifest[SCENES[alias]]
        out_dir = REPORT_ROOT / scene["id"]
        out_dir.mkdir(parents=True, exist_ok=True)
        config = write_config(scene)

        run(
            [
                str(BLENDER),
                "-b",
                scene["blend_file"],
                "--python",
                str(PIPELINE / "blender" / "prepare_osm_rail_scene_for_sionna.py"),
                "--",
                "--config",
                str(config),
                "--scene-id",
                scene["id"],
                "--terrain-type",
                scene["terrain_type"],
                "--sample-spacing-m",
                "25.0",
            ],
            out_dir / "01_prepare.log",
        )

        osm_path = OSM_DIR / f"{scene['id']}.osm"
        run(
            [
                str(BLENDER),
                "-b",
                str(out_dir / f"Train_{scene['id']}_report_visual.blend"),
                "--python",
                str(PIPELINE / "blender" / "add_report_visual_osm_context.py"),
                "--",
                "--config",
                str(config),
                "--osm",
                str(osm_path),
                "--bbox",
                ",".join(str(item) for item in scene["bbox"]),
            ],
            out_dir / "02_add_osm_context.log",
        )

        if scene["terrain_type"] in {"dam_pha_ven_bien", "deo_nui_ven_bien"} and not args.skip_dem:
            hgt = gunzip_dem()
            if hgt is not None:
                run(
                    [
                        str(BLENDER),
                        "-b",
                        str(out_dir / f"Train_{scene['id']}_report_visual.blend"),
                        "--python",
                        str(PIPELINE / "blender" / "add_srtm_dem_to_scene.py"),
                        "--",
                        "--config",
                        str(config),
                        "--scene-id",
                        scene["id"],
                        "--bbox",
                        ",".join(str(item) for item in scene["bbox"]),
                        "--hgt",
                        str(hgt),
                        "--grid",
                        "90",
                    ],
                    out_dir / "03_add_dem.log",
                )

        run(
            [
                str(BLENDER),
                "-b",
                str(out_dir / f"Train_{scene['id']}_report_visual.blend"),
                "--python",
                str(PIPELINE / "export" / "export_mitsuba.py"),
                "--",
                "--config",
                str(config),
            ],
            out_dir / "04_export_xml.log",
        )
        xml_path = out_dir / "scene.xml"
        add_colors_to_xml(xml_path)
        summary.append({"alias": alias, "scene_id": scene["id"], "config": str(config), "xml": str(xml_path)})

    (REPORT_ROOT / "report_visual_manifest.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
