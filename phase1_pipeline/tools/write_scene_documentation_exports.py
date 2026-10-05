from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from statistics import median


ROOT = Path(__file__).resolve().parents[1]
SCENE_DIR = ROOT / "vietnam_railway_osm_scenes"
OUT_DIR = ROOT / "scene_documentation_exports"

OUTPUT_DIRS = {
    "do_thi_day_dac_GiaiPhong-GiapBat": ROOT / "output_giai_phong_rt_full_sionna_final_physics",
    "do_thi_cau_song_LongBien-GiaLam": ROOT / "output_do_thi_cau_song_LongBien-GiaLam_full_sionna_final_physics",
    "dong_bang_cong_nghiep_HaiDuong-PhuThai": ROOT / "output_dong_bang_cong_nghiep_HaiDuong-PhuThai_full_sionna_final_physics",
    "do_thi_cang_bien_HaiPhong-ThuongLy": ROOT / "output_do_thi_cang_bien_HaiPhong-ThuongLy_full_sionna_final_physics",
    "dam_pha_ven_bien_LangCo-HaiVanBac": ROOT / "output_dam_pha_ven_bien_LangCo-HaiVanBac_full_sionna_final_physics",
    "deo_nui_ven_bien_HaiVanBac-HaiVanNam": ROOT / "output_deo_nui_ven_bien_HaiVanBac-HaiVanNam_full_sionna_final_physics",
}

SCENE_ORDER = [
    "do_thi_day_dac_GiaiPhong-GiapBat",
    "do_thi_cau_song_LongBien-GiaLam",
    "dong_bang_cong_nghiep_HaiDuong-PhuThai",
    "do_thi_cang_bien_HaiPhong-ThuongLy",
    "dam_pha_ven_bien_LangCo-HaiVanBac",
    "deo_nui_ven_bien_HaiVanBac-HaiVanNam",
]

TERRAIN_LABELS = {
    "do_thi_day_dac": "Do thi day dac",
    "do_thi_cau_song": "Do thi cau song",
    "dong_bang_cong_nghiep": "Dong bang/cong nghiep",
    "do_thi_cang_bien": "Do thi/cang bien",
    "dam_pha_ven_bien": "Dam pha/ven bien",
    "deo_nui_ven_bien": "Deo nui/ven bien",
}


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def station_name(index: int) -> str:
    letters = []
    i = index
    while True:
        letters.append(chr(ord("A") + (i % 26)))
        i = i // 26 - 1
        if i < 0:
            break
    return "GNB_" + "".join(reversed(letters))


def fmt_num(value, digits: int = 2) -> str:
    if value is None:
        return ""
    return f"{float(value):.{digits}f}"


def path_exists_text(path: str | None) -> str:
    if not path:
        return ""
    return "yes" if Path(path).exists() else "missing"


def clearance_items(raw):
    if isinstance(raw, dict):
        return raw.items()
    if isinstance(raw, list):
        pairs = []
        for i, item in enumerate(raw):
            if isinstance(item, dict):
                key = item.get("sample_index", item.get("sample", i))
                pairs.append((key, item))
            else:
                pairs.append((i, {"z_lift_m": item, "reason": ""}))
        return pairs
    return []


def scene_summary_stats(summary_items):
    return {item["scene_id"]: item for item in summary_items}


def manifest_by_scene(manifest_items):
    return {item["id"]: item for item in manifest_items}


def json_items(raw):
    if isinstance(raw, dict):
        return raw.get("value", raw)
    return raw


def trajectory_distance(samples):
    total = 0.0
    prev = None
    distances = []
    for point in samples:
        if prev is None:
            distances.append(0.0)
        else:
            dx = point[0] - prev[0]
            dy = point[1] - prev[1]
            dz = point[2] - prev[2]
            total += (dx * dx + dy * dy + dz * dz) ** 0.5
            distances.append(total)
        prev = point
    return distances


def make_report(scenes, manifest, summary, export_jobs):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# Mo ta chi tiet 6 scene Sionna RT",
        "",
        f"Ngay xuat: {now}",
        "",
        "File nay mo ta tung scene OSM/Blender da dung cho bo output Sionna RT final physics. "
        "Toa do gNB va UE trong cac bang ben duoi la toa do cuc bo Blender/Sionna tinh bang met, "
        "khong phai toa do GPS. UE duoc bieu dien bang chuoi `rx_trajectory_samples` bam theo duong ray "
        "tu OpenStreetMap; moi mau tuong ung mot snapshot ray-tracing.",
        "",
        "## Tong hop nhanh",
        "",
        "| Scene | Moi truong | Chieu dai ray (m) | RX/UE samples | gNB | Status | FBX output |",
        "|---|---|---:|---:|---:|---|---|",
    ]

    for scene_id in SCENE_ORDER:
        meta = scenes[scene_id]
        mani = manifest.get(scene_id, {})
        summ = summary.get(scene_id, {})
        job = export_jobs[scene_id]
        terrain = TERRAIN_LABELS.get(meta.get("terrain_type") or mani.get("terrain_type"), meta.get("terrain_type", ""))
        lines.append(
            "| {scene} | {terrain} | {length} | {rx} | {gnb} | {status} | `{fbx}` |".format(
                scene=scene_id,
                terrain=terrain,
                length=fmt_num(meta.get("track_length_m"), 1),
                rx=len(meta.get("rx_trajectory_samples", [])),
                gnb=len(meta.get("all_gnb_positions_m", [])),
                status=summ.get("status", ""),
                fbx=job["fbx"],
            )
        )

    lines.extend([
        "",
        "## Ghi chu chung",
        "",
        "- `source_blend`: file scene OSM ban dau.",
        "- `prepared_blend`: file da them rail marker/gNB/UE theo pipeline Sionna, duoc uu tien de export FBX.",
        "- `scene.xml`: scene da export sang Mitsuba/Sionna RT de ray-tracing.",
        "- Toc do tau trong bo output da chuan hoa ve `350 km/h`; Doppler cuc dai xap xi 9.73 kHz tai 30 GHz.",
        "- Power trong CSV la channel power tinh tu bien do complex, chua phai dBm tuyet doi neu chua gan link budget.",
        "",
    ])

    for scene_id in SCENE_ORDER:
        meta = scenes[scene_id]
        mani = manifest.get(scene_id, {})
        summ = summary.get(scene_id, {})
        terrain_key = meta.get("terrain_type") or mani.get("terrain_type")
        terrain = TERRAIN_LABELS.get(terrain_key, terrain_key or "")
        rx = meta.get("rx_trajectory_samples", [])
        gnb_positions = meta.get("all_gnb_positions_m", [])
        facing = meta.get("all_gnb_facing", [])
        distances = trajectory_distance(rx)
        sample_spacing = meta.get("sample_spacing_m")
        bbox = mani.get("bbox", [])
        bbox_text = ", ".join(fmt_num(v, 6) for v in bbox) if bbox else ""
        buildings = mani.get("building_count")
        max_height = mani.get("building_height_max_m")
        stations = summ.get("stations", [])
        best_segments = summ.get("best_gnb_segments", [])

        lines.extend([
            f"## {scene_id}",
            "",
            f"- Loai moi truong: {terrain}.",
            f"- Noi dung scene: {mani.get('railway_context', '')}",
            f"- Vai tro khoa hoc: {mani.get('scientific_role', '')}",
            f"- Bounding box OSM tham khao `(south, west, north, east)`: `{bbox_text}`.",
            f"- So mesh/building trong scene OSM goc: {mani.get('mesh_count', '')}/{buildings}; chieu cao building lon nhat xap xi {fmt_num(max_height, 1)} m.",
            f"- Chieu dai duong ray ray-tracing: {fmt_num(meta.get('track_length_m'), 1)} m.",
            f"- UE/RX samples: {len(rx)} mau; spacing danh nghia {fmt_num(sample_spacing, 1)} m.",
            f"- So gNB: {len(gnb_positions)}.",
            f"- Output Sionna: `{OUTPUT_DIRS[scene_id]}`.",
            f"- XML ray-tracing: `{OUTPUT_DIRS[scene_id] / 'scene.xml'}`.",
            f"- Source blend: `{meta.get('source_blend', '')}`.",
            f"- Prepared blend dung de export: `{meta.get('prepared_blend', '')}` ({path_exists_text(meta.get('prepared_blend'))}).",
            f"- FBX full scene: `{export_jobs[scene_id]['fbx']}`.",
            "",
            "### Vi tri gNB",
            "",
            "| gNB | x (m) | y (m) | z (m) | Facing | RX snapshots co path | Missing snapshots | Median path count | Median channel power (dB) |",
            "|---|---:|---:|---:|---|---:|---:|---:|---:|",
        ])

        for i, pos in enumerate(gnb_positions):
            st = stations[i] if i < len(stations) else {}
            lines.append(
                "| {name} | {x} | {y} | {z} | {face} | {snap} | {miss} | {paths} | {power} |".format(
                    name=station_name(i),
                    x=fmt_num(pos[0], 2),
                    y=fmt_num(pos[1], 2),
                    z=fmt_num(pos[2], 2),
                    face=facing[i] if i < len(facing) else "",
                    snap=st.get("snapshots", ""),
                    miss=st.get("missing_snapshots", ""),
                    paths=fmt_num(st.get("path_count_median"), 1) if st else "",
                    power=fmt_num(st.get("total_power_db_median"), 1) if st else "",
                )
            )

        if rx:
            xs = [p[0] for p in rx]
            ys = [p[1] for p in rx]
            zs = [p[2] for p in rx]
            first = rx[0]
            mid = rx[len(rx) // 2]
            last = rx[-1]
            lines.extend([
                "",
                "### UE / receiver trajectory",
                "",
                f"- UE bam theo rail object: `{meta.get('rail_object_name', '')}`.",
                f"- Diem dau UE: x={fmt_num(first[0])}, y={fmt_num(first[1])}, z={fmt_num(first[2])} m.",
                f"- Diem giua UE: x={fmt_num(mid[0])}, y={fmt_num(mid[1])}, z={fmt_num(mid[2])} m.",
                f"- Diem cuoi UE: x={fmt_num(last[0])}, y={fmt_num(last[1])}, z={fmt_num(last[2])} m.",
                f"- Bounding box UE cuc bo: x=[{fmt_num(min(xs))}, {fmt_num(max(xs))}] m; "
                f"y=[{fmt_num(min(ys))}, {fmt_num(max(ys))}] m; z=[{fmt_num(min(zs))}, {fmt_num(max(zs))}] m.",
                f"- Tong chieu dai tich luy tu cac sample UE: {fmt_num(distances[-1], 1)} m.",
                "- Toan bo diem UE/RX da duoc xuat trong `scene_ue_trajectory_samples.csv`.",
            ])

        if best_segments:
            lines.extend([
                "",
                "### Doan best-gNB theo ray",
                "",
                "| gNB tot nhat | start sample | end sample | start m | end m |",
                "|---|---:|---:|---:|---:|",
            ])
            for seg in best_segments:
                lines.append(
                    "| {station} | {start_idx} | {end_idx} | {start_m} | {end_m} |".format(
                        station=seg.get("station", ""),
                        start_idx=seg.get("start_idx", ""),
                        end_idx=seg.get("end_idx", ""),
                        start_m=fmt_num(seg.get("start_m"), 1),
                        end_m=fmt_num(seg.get("end_m"), 1),
                    )
                )

        if meta.get("dem"):
            dem = meta["dem"]
            lines.extend([
                "",
                "### DEM / dia hinh",
                "",
                f"- DEM da them: `{dem.get('source_hgt', '')}`.",
                f"- Object DEM trong scene: `{dem.get('object_name', '')}`.",
                f"- Luoi DEM: {dem.get('grid_rows', '')} x {dem.get('grid_cols', '')}; "
                f"elevation min/max: {fmt_num(dem.get('elevation_min_m'), 1)} / {fmt_num(dem.get('elevation_max_m'), 1)} m.",
            ])

        if meta.get("targeted_gap_gnbs"):
            lines.extend([
                "",
                "### GNB bo sung de lap gap",
                "",
            ])
            for item in meta["targeted_gap_gnbs"]:
                lines.append(
                    f"- {item.get('name', '')}: gan sample {item.get('sample_index', '')}, "
                    f"distance {fmt_num(item.get('track_distance_m'), 1)} m, "
                    f"position `{item.get('position_m', '')}`."
                )

        if meta.get("rx_clearance_corrections_m"):
            lines.extend([
                "",
                "### UE clearance corrections",
                "",
            ])
            for key, val in clearance_items(meta["rx_clearance_corrections_m"]):
                lines.append(f"- Sample {key}: nang z them {val.get('z_lift_m')} m; ly do: {val.get('reason', '')}.")

        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "fbx").mkdir(parents=True, exist_ok=True)

    manifest_raw = load_json(SCENE_DIR / "scene_manifest.json")
    manifest_items = json_items(manifest_raw)
    manifest = manifest_by_scene(manifest_items)

    summary_raw = load_json(ROOT / "output_all_scenes_final_physics_summary.json")
    summary_items = json_items(summary_raw)
    summary = scene_summary_stats(summary_items)

    scenes = {}
    export_jobs = {}
    for scene_id in SCENE_ORDER:
        meta_path = OUTPUT_DIRS[scene_id] / "scene_metadata.json"
        meta = load_json(meta_path)
        scenes[scene_id] = meta
        prepared = meta.get("prepared_blend") or meta.get("source_blend") or str(SCENE_DIR / f"{scene_id}.blend")
        if not Path(prepared).exists():
            prepared = meta.get("source_blend", prepared)
        fbx_path = OUT_DIR / "fbx" / f"{scene_id}_full_scene.fbx"
        export_jobs[scene_id] = {
            "scene_id": scene_id,
            "blend": str(Path(prepared)),
            "fbx": str(fbx_path),
            "metadata": str(meta_path),
            "output_dir": str(OUTPUT_DIRS[scene_id]),
        }

    report = make_report(scenes, manifest, summary, export_jobs)
    report_path = OUT_DIR / "scene_description_report.md"
    report_path.write_text(report, encoding="utf-8")

    gnb_csv = OUT_DIR / "scene_gnb_positions.csv"
    with gnb_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "scene_id",
                "gnb",
                "x_m",
                "y_m",
                "z_m",
                "facing",
                "snapshots_with_path",
                "missing_snapshots",
                "path_count_median",
                "channel_power_median_db",
            ],
        )
        writer.writeheader()
        for scene_id in SCENE_ORDER:
            meta = scenes[scene_id]
            stations = summary.get(scene_id, {}).get("stations", [])
            facing = meta.get("all_gnb_facing", [])
            for i, pos in enumerate(meta.get("all_gnb_positions_m", [])):
                st = stations[i] if i < len(stations) else {}
                writer.writerow(
                    {
                        "scene_id": scene_id,
                        "gnb": station_name(i),
                        "x_m": f"{pos[0]:.6f}",
                        "y_m": f"{pos[1]:.6f}",
                        "z_m": f"{pos[2]:.6f}",
                        "facing": facing[i] if i < len(facing) else "",
                        "snapshots_with_path": st.get("snapshots", ""),
                        "missing_snapshots": st.get("missing_snapshots", ""),
                        "path_count_median": st.get("path_count_median", ""),
                        "channel_power_median_db": st.get("total_power_db_median", ""),
                    }
                )

    ue_csv = OUT_DIR / "scene_ue_trajectory_samples.csv"
    with ue_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "scene_id",
                "sample_index",
                "distance_along_samples_m",
                "timestamp_ns_at_350kmh",
                "x_m",
                "y_m",
                "z_m",
            ],
        )
        writer.writeheader()
        speed_mps = 350_000.0 / 3600.0
        for scene_id in SCENE_ORDER:
            samples = scenes[scene_id].get("rx_trajectory_samples", [])
            distances = trajectory_distance(samples)
            for i, point in enumerate(samples):
                timestamp_ns = distances[i] / speed_mps * 1e9
                writer.writerow(
                    {
                        "scene_id": scene_id,
                        "sample_index": i,
                        "distance_along_samples_m": f"{distances[i]:.6f}",
                        "timestamp_ns_at_350kmh": f"{timestamp_ns:.3f}",
                        "x_m": f"{point[0]:.6f}",
                        "y_m": f"{point[1]:.6f}",
                        "z_m": f"{point[2]:.6f}",
                    }
                )

    manifest_path = OUT_DIR / "scene_export_manifest.json"
    manifest_path.write_text(json.dumps({"export_jobs": list(export_jobs.values())}, indent=2), encoding="utf-8")

    print(f"report={report_path}")
    print(f"gnb_csv={gnb_csv}")
    print(f"ue_csv={ue_csv}")
    print(f"manifest={manifest_path}")


if __name__ == "__main__":
    main()
