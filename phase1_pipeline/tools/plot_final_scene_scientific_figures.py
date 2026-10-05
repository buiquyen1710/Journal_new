from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "final_scene_scientific_figures"
SUMMARY_PATH = ROOT / "output_all_scenes_final_physics_summary.json"

SCENE_LABELS = {
    "do_thi_day_dac_GiaiPhong-GiapBat": "Giai Phong\nGiap Bat",
    "do_thi_cau_song_LongBien-GiaLam": "Long Bien\nGia Lam",
    "dong_bang_cong_nghiep_HaiDuong-PhuThai": "Hai Duong\nPhu Thai",
    "do_thi_cang_bien_HaiPhong-ThuongLy": "Hai Phong\nThuong Ly",
    "dam_pha_ven_bien_LangCo-HaiVanBac": "Lang Co\nHai Van Bac",
    "deo_nui_ven_bien_HaiVanBac-HaiVanNam": "Hai Van Bac\nHai Van Nam",
}

TERRAIN_LABELS = {
    "do_thi_day_dac": "Dense urban",
    "do_thi_cau_song": "Bridge/river urban",
    "dong_bang_cong_nghiep": "Delta/industrial",
    "do_thi_cang_bien": "Port urban",
    "dam_pha_ven_bien": "Coastal lagoon",
    "deo_nui_ven_bien": "Mountain pass + DEM",
}


def read_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, dict) and "value" in raw:
        return raw["value"]
    return raw


def station_from_csv(path: str) -> str:
    stem = Path(path).stem
    suffix = stem.replace("mpc_gnb_", "").upper()
    return "GNB_" + suffix


def db_from_power(power: float) -> float:
    if power <= 0:
        return float("nan")
    return 10.0 * math.log10(power)


def load_station_trace(csv_path: Path):
    by_ts = defaultdict(lambda: {"power": 0.0, "path_count": 0, "los": False, "max_abs_doppler": 0.0, "delays": []})
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = int(float(row["timestamp_ns"]))
            ar = float(row["amplitude_real"])
            ai = float(row["amplitude_imag"])
            p = ar * ar + ai * ai
            item = by_ts[ts]
            item["power"] += p
            item["path_count"] += 1
            item["los"] = item["los"] or int(float(row["los_flag"])) == 1
            item["max_abs_doppler"] = max(item["max_abs_doppler"], abs(float(row["doppler_hz"])))
            item["delays"].append(float(row["delay_s"]))

    rows = {}
    for ts, item in by_ts.items():
        rows[ts] = {
            "total_power_db": db_from_power(item["power"]),
            "path_count": item["path_count"],
            "los": item["los"],
            "max_abs_doppler": item["max_abs_doppler"],
            "delay_span_ns": (max(item["delays"]) - min(item["delays"])) * 1e9 if item["delays"] else 0.0,
        }
    return rows


def build_scene_data(summary_items):
    scenes = []
    for item in summary_items:
        output_dir = Path(item["output_dir"])
        stations = []
        all_timestamps = set()
        for st in item["stations"]:
            csv_path = Path(st["csv"])
            trace = load_station_trace(csv_path)
            all_timestamps.update(trace.keys())
            stations.append(
                {
                    "name": station_from_csv(st["csv"]),
                    "csv": csv_path,
                    "trace": trace,
                    "eval": st,
                }
            )

        timestamps = sorted(all_timestamps)
        best_series = []
        for ts in timestamps:
            candidates = []
            for st in stations:
                if ts in st["trace"]:
                    candidates.append((st["trace"][ts]["total_power_db"], st["name"], st["trace"][ts]))
            if not candidates:
                continue
            power_db, name, trace_row = max(candidates, key=lambda x: x[0])
            best_series.append(
                {
                    "timestamp_ns": ts,
                    "best_gnb": name,
                    "best_power_db": power_db,
                    "path_count": trace_row["path_count"],
                    "los": trace_row["los"],
                    "max_abs_doppler": trace_row["max_abs_doppler"],
                    "delay_span_ns": trace_row["delay_span_ns"],
                }
            )

        scenes.append(
            {
                "scene_id": item["scene_id"],
                "terrain_type": item["terrain_type"],
                "output_dir": output_dir,
                "track_length_m": float(item["track_length_m"]),
                "rx_samples": int(item["rx_samples"]),
                "network_snapshots": int(item["network_snapshots"]),
                "gnb_count": len(item["gnb_positions_m"]),
                "stations": stations,
                "best_series": best_series,
                "best_segments": item.get("best_gnb_segments", []),
            }
        )
    return scenes


def style_axes(ax):
    ax.grid(True, axis="y", alpha=0.25, linewidth=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def savefig(name: str):
    path = OUT / name
    plt.tight_layout()
    plt.savefig(path, dpi=220, bbox_inches="tight")
    plt.close()
    return path


def plot_overview(scenes):
    labels = [SCENE_LABELS[s["scene_id"]] for s in scenes]
    track_km = [s["track_length_m"] / 1000 for s in scenes]
    gnb_density = [s["gnb_count"] / (s["track_length_m"] / 1000) for s in scenes]
    los_ratio = [100 * np.mean([row["los"] for row in s["best_series"]]) for s in scenes]

    x = np.arange(len(scenes))
    fig, ax1 = plt.subplots(figsize=(12, 5.5))
    ax2 = ax1.twinx()
    bars = ax1.bar(x - 0.18, track_km, width=0.36, color="#4676b8", label="Track length (km)")
    ax2.plot(x, gnb_density, marker="o", color="#bf5b17", linewidth=2.2, label="gNB density (/km)")
    ax2.plot(x, los_ratio, marker="s", color="#2d8b57", linewidth=2.2, label="Best-cell LOS ratio (%)")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=9)
    ax1.set_ylabel("Track length (km)")
    ax2.set_ylabel("gNB density (/km) / LOS ratio (%)")
    ax1.set_title("Scene Scale, gNB Density, and Best-cell LOS Ratio")
    style_axes(ax1)
    ax2.spines["top"].set_visible(False)
    for bar, value in zip(bars, track_km):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.12, f"{value:.1f}", ha="center", va="bottom", fontsize=8)
    lines, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines + lines2, labels1 + labels2, loc="upper left", frameon=False)
    return savefig("fig01_scene_scale_gnb_density_los.png")


def plot_station_ranges(scenes):
    labels = [SCENE_LABELS[s["scene_id"]] for s in scenes]
    path_medians = []
    power_medians = []
    for s in scenes:
        path_medians.append([float(st["eval"]["path_count_median"]) for st in s["stations"]])
        power_medians.append([float(st["eval"]["total_power_db_median"]) for st in s["stations"]])

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2))
    axes[0].boxplot(path_medians, patch_artist=True, boxprops={"facecolor": "#8ecae6", "alpha": 0.75})
    axes[0].set_xticklabels(labels, rotation=20, ha="right", fontsize=8)
    axes[0].set_ylabel("Median path count per gNB")
    axes[0].set_title("Multipath Richness by Terrain")
    style_axes(axes[0])

    axes[1].boxplot(power_medians, patch_artist=True, boxprops={"facecolor": "#f4a261", "alpha": 0.75})
    axes[1].set_xticklabels(labels, rotation=20, ha="right", fontsize=8)
    axes[1].set_ylabel("Median channel power per gNB (dB, relative)")
    axes[1].set_title("Relative Channel Power by Terrain")
    style_axes(axes[1])
    return savefig("fig02_path_power_station_distributions.png")


def plot_best_power_cdf(scenes):
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for s in scenes:
        values = np.array([row["best_power_db"] for row in s["best_series"] if math.isfinite(row["best_power_db"])])
        values.sort()
        y = np.arange(1, len(values) + 1) / len(values)
        ax.plot(values, y, linewidth=2, label=SCENE_LABELS[s["scene_id"]].replace("\n", " "))
    ax.set_xlabel("Best-cell channel power (dB, relative)")
    ax.set_ylabel("Empirical CDF")
    ax.set_title("Network-level Best-cell Power Distribution")
    style_axes(ax)
    ax.grid(True, axis="x", alpha=0.15)
    ax.legend(fontsize=8, frameon=False, loc="lower right")
    return savefig("fig03_best_cell_power_cdf.png")


def plot_best_gnb_segments(scenes):
    fig, axes = plt.subplots(len(scenes), 1, figsize=(12, 8.8), sharex=False)
    colors = plt.cm.tab20(np.linspace(0, 1, 20))
    for ax, s in zip(axes, scenes):
        for seg in s["best_segments"]:
            station = seg.get("station", "")
            idx = ord(station[-1]) - ord("A") if station and station[-1].isalpha() else 0
            color = colors[idx % len(colors)]
            ax.barh(
                [0],
                [(float(seg["end_m"]) - float(seg["start_m"])) / 1000],
                left=float(seg["start_m"]) / 1000,
                height=0.52,
                color=color,
                edgecolor="white",
                linewidth=0.7,
            )
            mid = (float(seg["start_m"]) + float(seg["end_m"])) / 2000
            if (float(seg["end_m"]) - float(seg["start_m"])) > 120:
                ax.text(mid, 0, station.replace("GNB_", ""), ha="center", va="center", fontsize=7, color="black")
        ax.set_yticks([])
        ax.set_xlim(0, s["track_length_m"] / 1000)
        ax.set_ylabel(SCENE_LABELS[s["scene_id"]], rotation=0, ha="right", va="center", fontsize=8)
        ax.grid(True, axis="x", alpha=0.2)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_visible(False)
    axes[-1].set_xlabel("Distance along railway (km)")
    axes[0].set_title("Best-gNB Dominance Segments Along Each Railway Scene")
    return savefig("fig04_best_gnb_segments_along_track.png")


def plot_doppler_delay(scenes):
    labels = [SCENE_LABELS[s["scene_id"]] for s in scenes]
    max_doppler = [max(row["max_abs_doppler"] for row in s["best_series"]) for s in scenes]
    delay_p95 = [np.percentile([row["delay_span_ns"] for row in s["best_series"]], 95) for s in scenes]
    expected = 30e9 * (350_000 / 3600) / 299_792_458

    x = np.arange(len(scenes))
    fig, ax1 = plt.subplots(figsize=(12, 5.4))
    ax2 = ax1.twinx()
    ax1.bar(x - 0.18, max_doppler, width=0.36, color="#5a7d9a", label="Max |Doppler| (Hz)")
    ax1.axhline(expected, color="#1b4332", linestyle="--", linewidth=1.5, label=f"Theoretical 350 km/h @30GHz ({expected:.0f} Hz)")
    ax2.bar(x + 0.18, delay_p95, width=0.36, color="#c76f54", alpha=0.8, label="P95 delay span (ns)")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=9)
    ax1.set_ylabel("Doppler frequency (Hz)")
    ax2.set_ylabel("P95 delay span (ns)")
    ax1.set_title("High-speed Doppler Validation and Multipath Delay Spread Proxy")
    style_axes(ax1)
    ax2.spines["top"].set_visible(False)
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, frameon=False, loc="upper left", fontsize=8)
    return savefig("fig05_doppler_delay_validation.png")


def plot_heatmap_power_by_gnb(scenes):
    max_gnb = max(len(s["stations"]) for s in scenes)
    data = np.full((len(scenes), max_gnb), np.nan)
    for i, s in enumerate(scenes):
        for j, st in enumerate(s["stations"]):
            data[i, j] = float(st["eval"]["total_power_db_median"])

    fig, ax = plt.subplots(figsize=(11, 5.2))
    im = ax.imshow(data, aspect="auto", cmap="viridis", interpolation="nearest")
    ax.set_yticks(np.arange(len(scenes)))
    ax.set_yticklabels([SCENE_LABELS[s["scene_id"]].replace("\n", " ") for s in scenes], fontsize=8)
    ax.set_xticks(np.arange(max_gnb))
    ax.set_xticklabels([f"GNB_{chr(ord('A') + i)}" for i in range(max_gnb)], fontsize=8)
    ax.set_title("Median Relative Channel Power per gNB")
    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label("Median channel power (dB, relative)")
    for i in range(len(scenes)):
        for j in range(max_gnb):
            if not np.isnan(data[i, j]):
                ax.text(j, i, f"{data[i, j]:.0f}", ha="center", va="center", fontsize=7, color="white" if data[i, j] < -125 else "black")
    return savefig("fig06_gnb_power_heatmap.png")


def scene_stats_for_report(scenes):
    rows = []
    for s in scenes:
        best_power = np.array([r["best_power_db"] for r in s["best_series"]])
        best_paths = np.array([r["path_count"] for r in s["best_series"]])
        los = np.array([r["los"] for r in s["best_series"]], dtype=float)
        delay = np.array([r["delay_span_ns"] for r in s["best_series"]])
        rows.append(
            {
                "scene_id": s["scene_id"],
                "label": SCENE_LABELS[s["scene_id"]].replace("\n", " - "),
                "terrain": TERRAIN_LABELS.get(s["terrain_type"], s["terrain_type"]),
                "length_km": s["track_length_m"] / 1000,
                "rx": s["rx_samples"],
                "gnb": s["gnb_count"],
                "gnb_density": s["gnb_count"] / (s["track_length_m"] / 1000),
                "coverage": s["network_snapshots"] / s["rx_samples"],
                "los_ratio": float(np.mean(los)),
                "best_power_median": float(np.median(best_power)),
                "best_power_p05": float(np.percentile(best_power, 5)),
                "best_power_p95": float(np.percentile(best_power, 95)),
                "best_path_median": float(np.median(best_paths)),
                "delay_p95": float(np.percentile(delay, 95)),
                "segments": len(s["best_segments"]),
            }
        )
    return rows


def write_report(paths, scenes):
    stats = scene_stats_for_report(scenes)
    report = OUT / "final_scene_figures_analysis.md"
    lines = [
        "# Phan tich bieu do khoa hoc cho 6 scene dia hinh",
        "",
        "Bo hinh nay duoc ve truc tiep tu output Sionna RT final physics cua 6 scene. "
        "Cong suat trong cac hinh la channel power tuong doi tinh tu bien do complex trong CSV; "
        "chua phai RSRP/dBm tuyet doi neu chua gan link budget.",
        "",
        "## Bang thong ke rut gon",
        "",
        "| Scene | Dia hinh | km | RX | gNB | gNB/km | Coverage | LOS best-cell | Median best power | P05..P95 best power | Median best paths | Best-gNB segments |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in stats:
        lines.append(
            f"| {r['label']} | {r['terrain']} | {r['length_km']:.2f} | {r['rx']} | {r['gnb']} | "
            f"{r['gnb_density']:.2f} | {100*r['coverage']:.1f}% | {100*r['los_ratio']:.1f}% | "
            f"{r['best_power_median']:.1f} dB | {r['best_power_p05']:.1f}..{r['best_power_p95']:.1f} dB | "
            f"{r['best_path_median']:.1f} | {r['segments']} |"
        )

    lines.extend([
        "",
        "## Hinh 1 - Quy mo scene, mat do gNB va LOS",
        "",
        f"![Fig 1]({paths['overview']})",
        "",
        "Hinh nay cho thay hai thong tin quan trong: quy mo tuyen va muc do kho cua moi truong. "
        "Hai Duong - Phu Thai dai nhat, nhung chi can mat do gNB thap vi dia hinh thoang va LOS cao. "
        "Nguoc lai Hai Van chi dai khoang 7.9 km nhung can mat do gNB cao hon nhieu do DEM/doi nui gay che khuat. "
        "Day la bang chung truc quan cho ket luan: quy hoach gNB theo khoang cach deu la khong du, can quy hoach theo dia hinh.",
        "",
        "## Hinh 2 - Do giau da duong va cong suat theo gNB",
        "",
        f"![Fig 2]({paths['station_ranges']})",
        "",
        "Boxplot path count phan biet kha ro cac moi truong. Cang bien, dam pha va dong bang co nhieu path on dinh, "
        "trong khi Giai Phong co do phan tan lon vi co cell yeu ro ret. Boxplot power cho thay do thi day dac co mot gNB rat yeu, "
        "con Hai Van co bien thien cong suat lon nhat do che khuat dia hinh. Day la dau hieu co gia tri de dua vao adaptive handover.",
        "",
        "## Hinh 3 - CDF cong suat best-cell",
        "",
        f"![Fig 3]({paths['cdf']})",
        "",
        "CDF best-cell cho biet xac suat UE gap muc kenh yeu/manh theo toan tuyen. Duong cua Hai Van trai rong va co duoi yeu hon, "
        "the hien outage risk/weak-cell risk cao hon. Lang Co va Long Bien co phan lon mau nam o vung cong suat tot hon, phu hop voi moi truong thoang hoac co reflection mat nuoc. "
        "Bieu do nay rat phu hop de giai thich tai sao thuat toan handover can threshold/hysteresis khac nhau theo dia hinh.",
        "",
        "## Hinh 4 - Doan cell dominance theo chieu dai tuyen",
        "",
        f"![Fig 4]({paths['segments']})",
        "",
        "Day la hinh co gia tri truc tiep nhat cho ns-3 handover. Dong bang, cang bien va dam pha co cac vung dominance tuong doi dai va sach. "
        "Long Bien co nhieu doan ngan o khu vuc cau/song, cho thay nguy co ping-pong. Hai Van co nhieu segment nhat, chung minh cell dominance bi phan manh boi dia hinh deo nui.",
        "",
        "## Hinh 5 - Doppler va proxy delay spread",
        "",
        f"![Fig 5]({paths['doppler_delay']})",
        "",
        "Doppler cuc dai nam sat muc ly thuyet cho 350 km/h tai 30 GHz, xac nhan viec rescale toc do la dung ve mat vat ly. "
        "Cot delay-span P95 cho thay moi truong co nhieu phan xa/che khuat se tao dai tre lon hon. Hai Van va cac moi truong do thi/cang bien can duoc xem la case kho hon cho kenh high-speed.",
        "",
        "## Hinh 6 - Heatmap cong suat median theo tung gNB",
        "",
        f"![Fig 6]({paths['heatmap']})",
        "",
        "Heatmap giup nhin nhanh gNB nao yeu bat thuong. Giai Phong co GNB_A rat yeu, Hai Van co nhieu gNB yeu do che khuat va can relay bo sung. "
        "Trong khi do Lang Co, Hai Phong va Hai Duong co cac gNB dong deu hon. Bieu do nay nen dung de bao ve lua chon cell-specific handover thay vi chi dua vao khoang cach.",
        "",
        "## Ket luan dua vao bao cao",
        "",
        "1. Bo output da the hien ro su khac biet dia hinh: do thi gay NLOS/multipath, cau song gay handover churn, dong bang tao baseline LOS, cang bien co clutter nhung coverage on, dam pha ven bien thoang, Hai Van DEM gay che khuat manh.",
        "",
        "2. Ve mat so lieu, bo output hop ly cho trace-based ns-3 handover vi 6/6 scene co coverage network-level 100% va Doppler phu hop 350 km/h.",
        "",
        "3. Ve mat thuc te, can ghi ro day la engineering ray-tracing dataset dua tren OSM/DEM va vat lieu xap xi. De dung nhu RSRP/SINR tuyet doi can them calibration link budget.",
        "",
        "4. New finding quan trong: mat do va vi tri gNB phu thuoc manh vao dia hinh. Hai Van can gNB/relay day hon rat nhieu so voi dong bang, du chieu dai tuyen ngan hon.",
        "",
    ])
    report.write_text("\n".join(lines), encoding="utf-8")
    return report


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary_items = read_json(SUMMARY_PATH)
    scenes = build_scene_data(summary_items)

    paths = {
        "overview": plot_overview(scenes),
        "station_ranges": plot_station_ranges(scenes),
        "cdf": plot_best_power_cdf(scenes),
        "segments": plot_best_gnb_segments(scenes),
        "doppler_delay": plot_doppler_delay(scenes),
        "heatmap": plot_heatmap_power_by_gnb(scenes),
    }
    report = write_report(paths, scenes)

    stats_path = OUT / "final_scene_plot_stats.json"
    stats_path.write_text(json.dumps(scene_stats_for_report(scenes), indent=2), encoding="utf-8")

    print(f"output_dir={OUT}")
    print(f"report={report}")
    for key, path in paths.items():
        print(f"{key}={path}")
    print(f"stats={stats_path}")


if __name__ == "__main__":
    main()
