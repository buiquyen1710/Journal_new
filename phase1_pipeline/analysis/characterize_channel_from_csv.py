
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = PROJECT_ROOT / "phase1_pipeline" / "channel_characterization"

SCENARIOS = {
    "no_blockage": PROJECT_ROOT / "phase1_pipeline" / "output_unified",
    "with_train_blockage": PROJECT_ROOT / "phase1_pipeline" / "output_unified_train_blockage",
}

STATIONS = [
    ("TX1", "mpc_tx1_viaductA.csv", "Viaduct A"),
    ("TX2", "mpc_tx2_ground.csv", "Ground"),
    ("TX3", "mpc_tx3_tunnel.csv", "Tunnel"),
    ("TX4", "mpc_tx4_viaductF.csv", "Viaduct F"),
    ("TX5", "mpc_tx5_portal.csv", "Portal"),
]

EPS = 1e-300


def weighted_circular_spread_rad(angle_rad: np.ndarray, weight: np.ndarray) -> float:
    valid = np.isfinite(angle_rad) & np.isfinite(weight) & (weight > 0)
    if valid.sum() <= 1:
        return 0.0
    a = angle_rad[valid]
    w = weight[valid]
    sw = w.sum()
    if sw <= 0:
        return 0.0
    c = np.sum(w * np.cos(a)) / sw
    s = np.sum(w * np.sin(a)) / sw
    mean = math.atan2(s, c)
    diff = np.angle(np.exp(1j * (a - mean)))
    return float(np.sqrt(np.sum(w * diff * diff) / sw))


def weighted_linear_spread_rad(angle_rad: np.ndarray, weight: np.ndarray) -> float:
    valid = np.isfinite(angle_rad) & np.isfinite(weight) & (weight > 0)
    if valid.sum() <= 1:
        return 0.0
    a = angle_rad[valid]
    w = weight[valid]
    sw = w.sum()
    if sw <= 0:
        return 0.0
    mean = np.sum(w * a) / sw
    return float(np.sqrt(np.sum(w * (a - mean) ** 2) / sw))


def characterize_timestamp(group: pd.DataFrame) -> pd.Series:
    power = group["amplitude_real"].to_numpy(dtype=float) ** 2 + group["amplitude_imag"].to_numpy(dtype=float) ** 2
    total_power = float(np.sum(power))
    delay = group["delay_s"].to_numpy(dtype=float)
    if total_power <= 0:
        path_loss_db = np.nan
        mean_delay_s = np.nan
        rms_delay_spread_s = np.nan
    else:
        path_loss_db = -10.0 * math.log10(max(total_power, EPS))
        tau0 = float(np.nanmin(delay))
        excess_delay = delay - tau0
        mean_delay_s = float(np.sum(power * excess_delay) / total_power)
        rms_delay_spread_s = float(np.sqrt(np.sum(power * (excess_delay - mean_delay_s) ** 2) / total_power))

    los = group["los_flag"].to_numpy(dtype=int) if "los_flag" in group.columns else np.zeros(len(group), dtype=int)
    los_power = float(np.sum(power[los == 1]))
    nlos_power = float(np.sum(power[los != 1]))
    if los_power > 0 and nlos_power > 0:
        k_factor_db = 10.0 * math.log10(los_power / nlos_power)
    elif los_power > 0 and nlos_power <= 0:
        k_factor_db = np.inf
    else:
        k_factor_db = np.nan

    aoa_phi = group["aoa_phi_rad"].to_numpy(dtype=float)
    aod_phi = group["aod_phi_rad"].to_numpy(dtype=float)
    aoa_theta = group["aoa_theta_rad"].to_numpy(dtype=float)
    aod_theta = group["aod_theta_rad"].to_numpy(dtype=float)

    return pd.Series(
        {
            "path_count": int(len(group)),
            "total_power_linear": total_power,
            "path_loss_db": path_loss_db,
            "mean_excess_delay_s": mean_delay_s,
            "rms_delay_spread_s": rms_delay_spread_s,
            "rms_delay_spread_ns": rms_delay_spread_s * 1e9 if np.isfinite(rms_delay_spread_s) else np.nan,
            "asa_deg": math.degrees(weighted_circular_spread_rad(aoa_phi, power)),
            "asd_deg": math.degrees(weighted_circular_spread_rad(aod_phi, power)),
            "esa_deg": math.degrees(weighted_linear_spread_rad(aoa_theta, power)),
            "esd_deg": math.degrees(weighted_linear_spread_rad(aod_theta, power)),
            "los_power_linear": los_power,
            "nlos_power_linear": nlos_power,
            "k_factor_db": k_factor_db,
            "los_present": int(los_power > 0),
        }
    )


def summarize_time_series(df: pd.DataFrame, scenario: str, station: str, label: str) -> Dict[str, float | str | int]:
    finite_k = df["k_factor_db"].replace([np.inf, -np.inf], np.nan)
    finite_pl = df["path_loss_db"].replace([np.inf, -np.inf], np.nan)
    finite_ds = df["rms_delay_spread_ns"].replace([np.inf, -np.inf], np.nan)
    return {
        "scenario": scenario,
        "station": station,
        "label": label,
        "timestamps": int(len(df)),
        "avg_path_count": float(df["path_count"].mean()),
        "max_path_count": int(df["path_count"].max()),
        "los_timestamp_ratio": float(df["los_present"].mean()),
        "path_loss_db_mean": float(finite_pl.mean()),
        "path_loss_db_p05": float(finite_pl.quantile(0.05)),
        "path_loss_db_p50": float(finite_pl.quantile(0.50)),
        "path_loss_db_p95": float(finite_pl.quantile(0.95)),
        "rms_delay_spread_ns_mean": float(finite_ds.mean()),
        "rms_delay_spread_ns_p50": float(finite_ds.quantile(0.50)),
        "rms_delay_spread_ns_p95": float(finite_ds.quantile(0.95)),
        "asa_deg_mean": float(df["asa_deg"].mean()),
        "asd_deg_mean": float(df["asd_deg"].mean()),
        "esa_deg_mean": float(df["esa_deg"].mean()),
        "esd_deg_mean": float(df["esd_deg"].mean()),
        "k_factor_db_mean": float(finite_k.mean()),
        "k_factor_db_p50": float(finite_k.quantile(0.50)),
        "k_factor_db_p95": float(finite_k.quantile(0.95)),
    }


def plot_metric_by_station(metric_df: pd.DataFrame, scenario: str, metric: str, ylabel: str, filename: str) -> None:
    scenario_df = metric_df[metric_df["scenario"] == scenario]
    fig, ax = plt.subplots(figsize=(12, 6))
    for station, _, label in STATIONS:
        d = scenario_df[scenario_df["station"] == station].sort_values("timestamp_ns")
        if d.empty:
            continue
        time_s = (d["timestamp_ns"] - d["timestamp_ns"].min()) * 1e-9
        y = d[metric].replace([np.inf, -np.inf], np.nan)
        ax.plot(time_s, y, linewidth=1.0, label=f"{station} {label}")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.35)
    ax.legend(ncol=2, fontsize=8)
    ax.set_title(f"{ylabel} - {scenario}")
    fig.tight_layout()
    fig.savefig(OUTPUT_ROOT / filename, dpi=180)
    plt.close(fig)


def plot_angular_spreads(metric_df: pd.DataFrame, scenario: str) -> None:
    scenario_df = metric_df[metric_df["scenario"] == scenario]
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    metrics = [("asa_deg", "ASA"), ("asd_deg", "ASD"), ("esa_deg", "ESA"), ("esd_deg", "ESD")]
    for station, _, label in STATIONS:
        d = scenario_df[scenario_df["station"] == station].sort_values("timestamp_ns")
        if d.empty:
            continue
        time_s = (d["timestamp_ns"] - d["timestamp_ns"].min()) * 1e-9
        axes[0].plot(time_s, d["asa_deg"], linewidth=0.9, label=f"{station} ASA")
        axes[0].plot(time_s, d["asd_deg"], linewidth=0.9, linestyle="--", label=f"{station} ASD")
        axes[1].plot(time_s, d["esa_deg"], linewidth=0.9, label=f"{station} ESA")
        axes[1].plot(time_s, d["esd_deg"], linewidth=0.9, linestyle="--", label=f"{station} ESD")
    axes[0].set_ylabel("Azimuth spread (deg)")
    axes[1].set_ylabel("Elevation/zenith spread (deg)")
    axes[1].set_xlabel("Time (s)")
    for ax in axes:
        ax.grid(True, alpha=0.35)
        ax.legend(ncol=3, fontsize=7)
    fig.suptitle(f"Angular spreads - {scenario}")
    fig.tight_layout()
    fig.savefig(OUTPUT_ROOT / f"angular_spreads_{scenario}.png", dpi=180)
    plt.close(fig)




def plot_metric_by_station_distance(metric_df: pd.DataFrame, scenario: str, metric: str, ylabel: str, filename: str, speed_mps: float) -> None:
    scenario_df = metric_df[metric_df["scenario"] == scenario]
    fig, ax = plt.subplots(figsize=(12, 6))
    for station, _, label in STATIONS:
        d = scenario_df[scenario_df["station"] == station].sort_values("timestamp_ns")
        if d.empty:
            continue
        dist_m = (d["timestamp_ns"] - d["timestamp_ns"].min()) * 1e-9 * speed_mps
        y = d[metric].replace([np.inf, -np.inf], np.nan)
        ax.plot(dist_m, y, linewidth=1.0, label=f"{station} {label}")
    ax.set_xlabel("Train travel distance from first snapshot (m)")
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.35)
    ax.legend(ncol=2, fontsize=8)
    ax.set_title(f"{ylabel} vs distance - {scenario}")
    fig.tight_layout()
    fig.savefig(OUTPUT_ROOT / filename, dpi=180)
    plt.close(fig)


def plot_angular_spreads_distance(metric_df: pd.DataFrame, scenario: str, speed_mps: float) -> None:
    scenario_df = metric_df[metric_df["scenario"] == scenario]
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    for station, _, label in STATIONS:
        d = scenario_df[scenario_df["station"] == station].sort_values("timestamp_ns")
        if d.empty:
            continue
        dist_m = (d["timestamp_ns"] - d["timestamp_ns"].min()) * 1e-9 * speed_mps
        axes[0].plot(dist_m, d["asa_deg"], linewidth=0.9, label=f"{station} ASA")
        axes[0].plot(dist_m, d["asd_deg"], linewidth=0.9, linestyle="--", label=f"{station} ASD")
        axes[1].plot(dist_m, d["esa_deg"], linewidth=0.9, label=f"{station} ESA")
        axes[1].plot(dist_m, d["esd_deg"], linewidth=0.9, linestyle="--", label=f"{station} ESD")
    axes[0].set_ylabel("Azimuth spread (deg)")
    axes[1].set_ylabel("Elevation/zenith spread (deg)")
    axes[1].set_xlabel("Train travel distance from first snapshot (m)")
    for ax in axes:
        ax.grid(True, alpha=0.35)
        ax.legend(ncol=3, fontsize=7)
    fig.suptitle(f"Angular spreads vs distance - {scenario}")
    fig.tight_layout()
    fig.savefig(OUTPUT_ROOT / f"paper_style_angular_spreads_distance_{scenario}.png", dpi=180)
    plt.close(fig)

def plot_summary_bars(summary: pd.DataFrame) -> None:
    metrics = [
        ("path_loss_db_mean", "Mean path loss (dB)", "summary_mean_path_loss_db.png"),
        ("rms_delay_spread_ns_mean", "Mean RMS delay spread (ns)", "summary_mean_delay_spread_ns.png"),
        ("asa_deg_mean", "Mean ASA (deg)", "summary_mean_asa_deg.png"),
        ("k_factor_db_mean", "Mean K-factor (dB)", "summary_mean_k_factor_db.png"),
    ]
    for metric, ylabel, filename in metrics:
        pivot = summary.pivot(index="station", columns="scenario", values=metric).reindex([s[0] for s in STATIONS])
        fig, ax = plt.subplots(figsize=(10, 5))
        pivot.plot(kind="bar", ax=ax)
        ax.set_ylabel(ylabel)
        ax.set_xlabel("Station")
        ax.grid(True, axis="y", alpha=0.35)
        ax.set_title(ylabel + " by scenario")
        fig.tight_layout()
        fig.savefig(OUTPUT_ROOT / filename, dpi=180)
        plt.close(fig)


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    all_metrics: List[pd.DataFrame] = []
    summaries: List[Dict[str, float | str | int]] = []

    for scenario, scenario_dir in SCENARIOS.items():
        if not scenario_dir.exists():
            print(f"Skip missing scenario: {scenario_dir}")
            continue
        for station, filename, label in STATIONS:
            csv_path = scenario_dir / filename
            if not csv_path.exists():
                print(f"Skip missing CSV: {csv_path}")
                continue
            print(f"Processing {scenario} {station}: {csv_path.name}")
            df = pd.read_csv(csv_path)
            metrics = df.groupby("timestamp_ns", sort=True, group_keys=False).apply(characterize_timestamp).reset_index()
            metrics.insert(0, "scenario", scenario)
            metrics.insert(1, "station", station)
            metrics.insert(2, "label", label)
            metrics_path = OUTPUT_ROOT / f"channel_metrics_{scenario}_{station}.csv"
            metrics.to_csv(metrics_path, index=False)
            all_metrics.append(metrics)
            summaries.append(summarize_time_series(metrics, scenario, station, label))

    if not all_metrics:
        raise SystemExit("No metrics generated")

    metric_df = pd.concat(all_metrics, ignore_index=True)
    metric_df.to_csv(OUTPUT_ROOT / "channel_metrics_all_scenarios.csv", index=False)
    summary_df = pd.DataFrame(summaries)
    summary_df.to_csv(OUTPUT_ROOT / "channel_characterization_summary.csv", index=False)
    (OUTPUT_ROOT / "channel_characterization_summary.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    speed_mps = 350.0 / 3.6
    for scenario in sorted(metric_df["scenario"].unique()):
        plot_metric_by_station(metric_df, scenario, "path_loss_db", "Effective path loss (dB)", f"path_loss_{scenario}.png")
        plot_metric_by_station(metric_df, scenario, "rms_delay_spread_ns", "RMS delay spread (ns)", f"delay_spread_{scenario}.png")
        plot_metric_by_station(metric_df, scenario, "k_factor_db", "Ricean K-factor (dB)", f"k_factor_{scenario}.png")
        plot_angular_spreads(metric_df, scenario)
        plot_metric_by_station_distance(metric_df, scenario, "path_loss_db", "Effective path loss (dB)", f"paper_style_path_loss_distance_{scenario}.png", speed_mps)
        plot_metric_by_station_distance(metric_df, scenario, "rms_delay_spread_ns", "RMS delay spread (ns)", f"paper_style_delay_spread_distance_{scenario}.png", speed_mps)
        plot_metric_by_station_distance(metric_df, scenario, "k_factor_db", "Ricean K-factor (dB)", f"paper_style_k_factor_distance_{scenario}.png", speed_mps)
        plot_angular_spreads_distance(metric_df, scenario, speed_mps)
    plot_summary_bars(summary_df)

    print(f"Wrote outputs to: {OUTPUT_ROOT}")
    print(summary_df.to_string(index=False))


if __name__ == "__main__":
    main()
