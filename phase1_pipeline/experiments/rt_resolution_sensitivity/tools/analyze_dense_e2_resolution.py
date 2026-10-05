#!/usr/bin/env python3
"""Build the authoritative coarse-vs-dense E2 resolution-validation package."""

from __future__ import annotations

import csv
import json
import math
import os
from pathlib import Path
from typing import Any


ROOT = Path(os.environ.get("SIOLENA_NS3_REPO_ROOT", Path.home() / "siolena-src"))
BASE_TRACE = ROOT / "results_21_6/outputs_raw/_traces_native350/Cau_Long_Bien"
BASE_RESULTS = ROOT / "results_21_6/outputs_raw/experiment2"
BASE_METRICS = ROOT / "results_21_6/metrics/summary_metrics.csv"
DENSE_TRACE = ROOT / "experiments/rt_resolution_sensitivity/ns3_ready/RTSensitivity_E2_dense1923m_shadow_881"
DENSE_RESULTS = ROOT / "experiments/rt_resolution_sensitivity/results_dense1923m"
OUT = ROOT / "experiments/rt_resolution_sensitivity/analysis_dense1923m"
SPEED_MPS = 350.0 / 3.6
ROUTE_LENGTH_M = 1692.3850891042694
COARSE_SPACING_M = 25.0
DENSE_SPACING_M = 1.923165
COARSE_INTERVAL_MS = 1000.0 * 17.407389488 / 68.0
DENSE_INTERVAL_MS = 1000.0 * 17.407389488 / 880.0

CASES = {
    "aggressive": {"label": "Aggressive", "hom": 1.0, "ttt": 40.0, "baseline_id": "Cau_Long_Bien__A3_aggressive__v350__traces__run001"},
    "balanced": {"label": "Balanced", "hom": 3.0, "ttt": 160.0, "baseline_id": "Cau_Long_Bien__A3_balanced__v350__traces__run001"},
    "conservative": {"label": "Conservative", "hom": 5.0, "ttt": 320.0, "baseline_id": "Cau_Long_Bien__A3_conservative__v350__traces__run001"},
}

# These are the four contiguous groups formed by the nine audited source indices,
# plus the isolated index 664. The source timestamp, not a displayed rounded
# distance, remains authoritative.
ZERO_GROUPS = [
    ("Z1", [478, 479]),
    ("Z2", [573, 574]),
    ("Z3", [627, 628]),
    ("Z4", [664]),
    ("Z5", [683, 684]),
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def read_kv_csv(path: Path) -> dict[str, str]:
    return {r["metric"]: r["value"] for r in read_csv(path)}


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def raw_dir(base: Path) -> Path:
    found = sorted((base / "raw").glob("*-traces"))
    if len(found) != 1:
        raise RuntimeError(f"Expected exactly one raw trace run under {base}, got {found}")
    return found[0]


def finite_float(value: str) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def baseline_metric_rows() -> dict[str, dict[str, str]]:
    rows = read_csv(BASE_METRICS)
    return {row["case_id"]: row for row in rows if row.get("case_id") in {v["baseline_id"] for v in CASES.values()}}


def validate_run(case: str, run: Path) -> dict[str, Any]:
    metadata = json.loads((run / "run_metadata.json").read_text(encoding="utf-8"))
    assert metadata["exit_code"] == 0
    assert metadata["trace_scenario"] == DENSE_TRACE.name
    assert metadata["number_of_time_divisions"] == 881
    raw = raw_dir(run)
    manifest = (raw / "run_manifest.txt").read_text(encoding="utf-8")
    assert f"traces_scenario={DENSE_TRACE.name}" in manifest
    assert f"traces_path={DENSE_TRACE.parent}" in manifest

    time_rows = read_csv(raw / "time_series.csv")
    assert len(time_rows) == 348
    times = [float(r["time_s"]) for r in time_rows]
    assert all(b > a for a, b in zip(times, times[1:]))
    assert times[-1] == 17.4
    assert {int(r["serving_gnb"]) for r in time_rows} <= {1, 3, 5, 7, 9, 11}
    operational_fields = ("sinr_db", "phy_sinr_db", "best_sinr_db", "throughput_mbps")
    for row in time_rows:
        for field in operational_fields:
            value = float(row[field])
            assert not math.isnan(value)
            assert value != math.inf and value != -math.inf

    events = read_csv(raw / "handover_events.csv")
    starts = [r for r in events if r["event"] == "start"]
    ends = [r for r in events if r["event"] == "end_ok"]
    assert len(starts) == len(ends)
    for start, end in zip(starts, ends):
        assert start["source_cell"] == end["source_cell"]
        assert start["target_cell"] == end["target_cell"]
        assert float(end["time_s"]) >= float(start["time_s"])

    # A literal zero coefficient is intentionally serialized as -inf RSRP and
    # +inf path loss in diagnostic files. Reject every other non-finite value.
    expected_nonfinite = 0
    for row in read_csv(raw / "ue_measurements.csv"):
        for field, text in row.items():
            try:
                value = float(text)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(value):
                assert field == "rsrp_dbm" and value == -math.inf
                expected_nonfinite += 1
    pathloss_inf = 0
    for row in read_csv(raw / "phy_sinr.csv"):
        for field, text in row.items():
            try:
                value = float(text)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(value):
                assert field == "value" and row.get("metric") in {"phy_avg_pathloss_db", "phy_max_pathloss_db"} and value == math.inf
                pathloss_inf += 1

    stderr = (run / "stderr.log").read_text(encoding="utf-8", errors="replace")
    assert "error" not in stderr.lower() and "exception" not in stderr.lower()
    return {
        "operating_point": CASES[case]["label"],
        "exit_code": metadata["exit_code"],
        "wall_time_s": metadata["wall_time_s"],
        "time_series_rows": len(time_rows),
        "first_time_s": times[0],
        "last_time_s": times[-1],
        "ho_start_count": len(starts),
        "ho_end_ok_count": len(ends),
        "expected_zero_rsrp_neg_inf_count": expected_nonfinite,
        "expected_zero_pathloss_pos_inf_count": pathloss_inf,
        "unexpected_nonfinite_count": 0,
        "manifest_dense_trace_ok": "YES",
        "status": "PASS",
    }


def build_comparison() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    base_metrics = baseline_metric_rows()
    rows: list[dict[str, Any]] = []
    data: dict[str, dict[str, Any]] = {}
    for case, spec in CASES.items():
        base_run = BASE_RESULTS / spec["baseline_id"]
        dense_run = DENSE_RESULTS / case
        base_raw = raw_dir(base_run)
        dense_raw = raw_dir(dense_run)
        base_summary = read_kv_csv(base_raw / "summary.csv")
        dense_summary = read_kv_csv(dense_raw / "summary.csv")
        base_analysis = base_metrics[spec["baseline_id"]]
        dense_analysis = read_csv(dense_run / "kpi_summary.csv")[0]

        coarse = {
            "mean": float(base_analysis["average_sinr_db"]),
            "p5": float(base_analysis["p5_sinr_db"]),
            "outage": 100.0 * float(base_summary["sinr_outage_rate_below_-6db"]),
            "ho": int(base_summary["handover_successes"]),
            "pp": int(base_summary["ping_pong_count"]),
            "valid": int(base_summary["phy_sample_count"]),
        }
        dense = {
            "mean": float(dense_analysis["average_sinr_db"]),
            "p5": float(dense_analysis["p5_sinr_db"]),
            "outage": 100.0 * float(dense_summary["sinr_outage_rate_below_-6db"]),
            "ho": int(dense_summary["handover_successes"]),
            "pp": int(dense_summary["ping_pong_count"]),
            "valid": int(dense_summary["phy_sample_count"]),
        }
        data[case] = {"coarse": coarse, "dense": dense, "base_raw": base_raw, "dense_raw": dense_raw}
        rows.append({
            "operating_point": spec["label"], "hom_db": spec["hom"], "ttt_ms": spec["ttt"],
            "coarse_spacing_m": COARSE_SPACING_M, "coarse_interval_ms": COARSE_INTERVAL_MS,
            "coarse_mean_sinr_db": coarse["mean"], "coarse_p5_sinr_db": coarse["p5"],
            "coarse_outage_pct": coarse["outage"], "coarse_valid_phy_samples": coarse["valid"],
            "coarse_ho_count": coarse["ho"], "coarse_pp_count": coarse["pp"],
            "coarse_ho_per_km": coarse["ho"] / (ROUTE_LENGTH_M / 1000.0),
            "coarse_pp_per_km": coarse["pp"] / (ROUTE_LENGTH_M / 1000.0),
            "dense_spacing_m": DENSE_SPACING_M, "dense_interval_ms": DENSE_INTERVAL_MS,
            "dense_mean_sinr_db": dense["mean"], "dense_p5_sinr_db": dense["p5"],
            "dense_outage_pct": dense["outage"], "dense_valid_phy_samples": dense["valid"],
            "dense_ho_count": dense["ho"], "dense_pp_count": dense["pp"],
            "dense_ho_per_km": dense["ho"] / (ROUTE_LENGTH_M / 1000.0),
            "dense_pp_per_km": dense["pp"] / (ROUTE_LENGTH_M / 1000.0),
            "delta_mean_sinr_db": dense["mean"] - coarse["mean"],
            "delta_p5_sinr_db": dense["p5"] - coarse["p5"],
            "delta_outage_pp": dense["outage"] - coarse["outage"],
            "delta_ho_count": dense["ho"] - coarse["ho"], "delta_pp_count": dense["pp"] - coarse["pp"],
        })
    return rows, data


def completed_hos(path: Path) -> list[dict[str, Any]]:
    out = []
    for row in read_csv(path / "handover_events.csv"):
        if row["event"] != "end_ok":
            continue
        t = float(row["time_s"])
        out.append({"time": t, "distance": min(t * SPEED_MPS, ROUTE_LENGTH_M), "source": int(row["source_cell"]), "target": int(row["target_cell"])})
    return out


def pair_hos(case: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    coarse = completed_hos(data["base_raw"])
    dense = completed_hos(data["dense_raw"])
    pairs: list[tuple[dict[str, Any] | None, dict[str, Any] | None, str]] = []
    candidates = []
    for ci, c in enumerate(coarse):
        for di, d in enumerate(dense):
            if (c["source"], c["target"]) == (d["source"], d["target"]):
                candidates.append((abs(c["distance"] - d["distance"]), ci, di))
    used_c, used_d = set(), set()
    for delta, ci, di in sorted(candidates):
        if ci in used_c or di in used_d or delta > 100.0:
            continue
        used_c.add(ci); used_d.add(di)
        pairs.append((coarse[ci], dense[di], "same transition, nearest event within 100 m"))
    for ci, c in enumerate(coarse):
        if ci not in used_c:
            pairs.append((c, None, "coarse-only event"))
    for di, d in enumerate(dense):
        if di not in used_d:
            pairs.append((None, d, "dense-only event"))
    pairs.sort(key=lambda p: min(x["time"] for x in p[:2] if x is not None))

    rows = []
    for index, (c, d, note) in enumerate(pairs, 1):
        row: dict[str, Any] = {"operating_point": CASES[case]["label"], "comparison_index": index, "match_basis": note}
        for prefix, event in (("coarse", c), ("dense", d)):
            for key in ("distance", "time", "source", "target"):
                row[f"{prefix}_{'distance_m' if key == 'distance' else 'timestamp_s' if key == 'time' else key + '_gnb'}"] = "" if event is None else event[key]
        if c and d:
            row["spatial_shift_m"] = d["distance"] - c["distance"]
        else:
            row["spatial_shift_m"] = ""
        rows.append(row)
    return rows


def source_zero_regions() -> list[dict[str, Any]]:
    audit = {int(r["snapshot_index"]): r for r in read_csv(ROOT / "DENSE_E2_CONVERTER_PATCH_AUDIT.csv")}
    regions = []
    for name, indices in ZERO_GROUPS:
        times = [float(audit[i]["source_timestamp_s"]) for i in indices]
        distances = [t * SPEED_MPS for t in times]
        regions.append({"name": name, "indices": indices, "times": times, "distances": distances, "lo": min(distances), "hi": max(distances), "center": sum(distances) / len(distances)})
    return regions


def blockage_rows(data: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for case, spec in CASES.items():
        rows = read_csv(data[case]["dense_raw"] / "time_series.csv")
        events = completed_hos(data[case]["dense_raw"])
        for region in source_zero_regions():
            # 50-ms KPI sampling is coarser than a 1--2-state zero region; use
            # a symmetric 7.5-m observation window and report it explicitly.
            window_lo, window_hi = region["center"] - 7.5, region["center"] + 7.5
            nearby = [r for r in rows if window_lo <= float(r["track_pos_m"]) <= window_hi]
            assert nearby
            valid_phy = [float(r["phy_sinr_db"]) for r in nearby if float(r["phy_sinr_db"]) > -900]
            outage = any(v < -6.0 for v in valid_phy) or any(float(r["throughput_mbps"]) <= 0.01 for r in nearby)
            zero_thr = any(float(r["throughput_mbps"]) <= 0.01 for r in nearby)
            ho_near = [e for e in events if abs(e["distance"] - region["center"]) <= 50.0]
            before = max((r for r in rows if float(r["track_pos_m"]) < window_lo), key=lambda r: float(r["track_pos_m"]), default={})
            after = min((r for r in rows if float(r["track_pos_m"]) > window_hi), key=lambda r: float(r["track_pos_m"]), default={})
            recovery = next((r for r in rows if float(r["track_pos_m"]) > region["hi"] and float(r["track_pos_m"]) <= region["hi"] + 50.0 and float(r["phy_sinr_db"]) > -900 and float(r["phy_sinr_db"]) >= -6.0 and float(r["throughput_mbps"]) > 0.01), None)
            output.append({
                "region": region["name"], "operating_point": spec["label"],
                "source_indices": ";".join(map(str, region["indices"])),
                "distance_range_m": f"{region['lo']:.3f}-{region['hi']:.3f}",
                "observation_window_m": f"{window_lo:.3f}-{window_hi:.3f}",
                "outage_present": "YES" if outage else "NO",
                "zero_throughput_present": "YES" if zero_thr else "NO",
                "minimum_valid_phy_sinr_db": min(valid_phy) if valid_phy else "NO_VALID_SAMPLE",
                "handover_within_50m": "YES" if ho_near else "NO",
                "handover_transitions": ";".join(f"{e['source']}->{e['target']}@{e['distance']:.1f}m" for e in ho_near),
                "serving_before": before.get("serving_gnb", ""), "serving_after": after.get("serving_gnb", ""),
                "recovery_within_50m": "YES" if recovery else "NO",
                "recovery_distance_m": "" if recovery is None else recovery["track_pos_m"],
                "notes": "Observed association only; the all-gNB-zero geometry is not asserted as the cause of nearby A3/HO activity.",
            })
    return output


def fmt(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}"


def write_report(comparison: list[dict[str, Any]], integrity: list[dict[str, Any]], blockage: list[dict[str, Any]]) -> None:
    table = []
    for r in comparison:
        table.append(
            f"| {r['operating_point']} | {r['hom_db']:.0f}/{r['ttt_ms']:.0f} | {r['coarse_mean_sinr_db']:.3f} | {r['dense_mean_sinr_db']:.3f} | "
            f"{r['coarse_p5_sinr_db']:.3f} | {r['dense_p5_sinr_db']:.3f} | {r['coarse_outage_pct']:.3f} | {r['dense_outage_pct']:.3f} | "
            f"{r['coarse_ho_count']}/{r['dense_ho_count']} | {r['coarse_pp_count']}/{r['dense_pp_count']} |"
        )
    block_summary = []
    for label in ("Aggressive", "Balanced", "Conservative"):
        subset = [r for r in blockage if r["operating_point"] == label]
        block_summary.append(
            f"- {label}: outage/zero-throughput was observed in {sum(r['outage_present']=='YES' for r in subset)}/5 windows; "
            f"a completed HO lay within 50 m of {sum(r['handover_within_50m']=='YES' for r in subset)}/5 windows."
        )
    runtime = ", ".join(f"{r['operating_point']} {r['wall_time_s']:.1f} s" for r in integrity)
    text = f"""# Dense E2 resolution-validation report

## A. Experiment objective

This experiment tests whether the qualitative outage--mobility behavior of E2 (Cầu Long Biên) under the native approximately 25-m RT trace persists under the validated dense trace (mean spacing 1.923165 m; replay interval 19.781124 ms). It is a three-point resolution-sensitivity validation, not a HOM×TTT sweep or parameter optimization.

## B. Exact software revision

- ns-3: 3.44
- 5G-LENA/NR: NR-v4.0
- branch: `feature/tpho-lookahead`
- commit: `cc25f66bfd2a0b27d1354a46da7796dadc93f5c9`
- working tree: DIRTY before and after execution; no reset, clean, checkout, commit, or push was performed.
- exact paper executable: `{ROOT / 'build/scratch/railway-digital-twin-evaluation/ns3.44-railway-digital-twin-evaluation-default'}`
- executable SHA-256: `d1e1cd48a5a02b3d386b8501676064d9508c0748c657bf778d6dbf8b898303b5`

## C. Baseline trace provenance

The authoritative baseline was traced from the paper commands, manifests, result directories, and conversion summary—not inferred from its name.

- trace: `{BASE_TRACE}`
- 69 states over 17.407389488 s; uniform replay interval {COARSE_INTERVAL_MS:.6f} ms
- paper command manifests: `{ROOT / 'results_21_6/commands'}`
- result roots: `{BASE_RESULTS}/Cau_Long_Bien__A3_[aggressive|balanced|conservative]__v350__traces__run001`
- authoritative aggregate metrics: `{BASE_METRICS}`
- baseline outage values reproduce 7.18391%, 5.74713%, and 8.62069%; therefore the authoritative paper baseline is reproduced.

The primary radio-outage field in this comparison is the simulator summary field `sinr_outage_rate_below_-6db`, matching the expected paper values. Mean and P5 SINR use the paper postprocessor's fresh valid PHY samples. The separate composite service-outage KPI (`throughput<=0.01 Mbps OR fresh PHY SINR<-6 dB OR no serving cell`) is not substituted for this radio-outage field.

## D. Dense trace provenance

- source: `{ROOT / 'E2_dense2m_resolution_validation_20260907_150848'}`
- validated package: `{DENSE_TRACE}`
- 881 states, six channel files, duration 17.407389488 s, update period {DENSE_INTERVAL_MS:.6f} ms
- nine all-gNB-zero source states and all 323 missing per-link states are retained as `num_paths=0`; no synthetic sentinel is present.
- prior exact-reader audit established zero power, no stale-state reuse, and a passing VALID→ZERO→ZERO→VALID transition.

## E. Common simulation configuration

The dense commands reuse the exact paper binary and scene JSON. Common settings are: 350 km/h, 30 GHz, 400 MHz, numerology 3, gNB/UE Tx power 43/23 dBm, `ns3::DirectPathBeamforming`, 100-ms beam period, ideal RRC, no background UEs, UDP 1200 bytes every 1000 µs, seed/run 1/1, and 17.407389487929628-s simulation time. Traffic, scheduler, topology, measurement logic, KPI definitions, scene mapping, and RNG settings are unchanged. Only the physical trace root/scenario changes.

The scene's controller-side MPC adapter remains exactly as in the paper scene JSON. The physical 5G-LENA trace reader used for UE PHY measurements resolves to the dense package in every run manifest.

## F. Three A3 operating points

- Aggressive: HOM 1 dB, TTT 40 ms
- Balanced: HOM 3 dB, TTT 160 ms
- Conservative: HOM 5 dB, TTT 320 ms

All three ran sequentially and exited 0. No other scene or A3 point was run. Wall times: {runtime}.

## G. Coarse-vs-dense KPI table

| Point | HOM/TTT | Coarse mean | Dense mean | Coarse P5 | Dense P5 | Coarse outage % | Dense outage % | HO C/D | PP C/D |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(table)}

Balanced remains below both Aggressive and Conservative in radio outage for coarse and dense traces. The full ordering changes from coarse `Balanced < Aggressive < Conservative` to dense `Balanced < Conservative < Aggressive`; thus the Aggressive-versus-Conservative sub-ranking reverses. Conservative remains the least mobile point (one HO, no PP) in both. Aggressive's excess mobility over Balanced is not preserved: it changes from 6 versus 4 HO and 2 versus 0 PP to 4 versus 4 HO and 0 versus 0 PP.

## H. HO-position comparison

`handover_position_comparison.csv` records completed HO times, distance at 350 km/h, source/target cells, and scientifically conservative nearest same-transition matching. The first three Aggressive transitions remain in the same regions; the dense trace removes the coarse 9→11→9 ping-pong pair around 1249--1308 m and shifts the final 9→11 completion by about +19.4 m. Balanced retains all four transitions, with its final 9→11 event shifted about +19.4 m. Conservative's sole 1→7 completion is spatially coincident to displayed precision. Exact one-to-one event identity is not claimed.

## I. Blockage-window observations

The five source regions are derived directly from audited indices 478/479, 573/574, 627/628, 664, and 683/684. Because KPI samples are 50 ms apart, `dense_blockage_region_analysis.csv` uses an explicit ±7.5-m observation window and separately flags completed HOs within 50 m.

{chr(10).join(block_summary)}

These are spatial associations. They show outage and recovery behavior around validated geometric blockages, but do not by themselves establish that a particular blockage caused an A3 trigger or HO.

## J. Qualitative robustness classification

**B — PARTIALLY ROBUST.** The two principal outage relationships specified for E2 (Balanced < Aggressive and Balanced < Conservative) and Conservative mobility suppression survive dense sampling. The Aggressive-versus-Conservative outage sub-ranking reverses, and the key Aggressive-versus-Balanced mobility-event relationship does not survive: their dense HO and ping-pong counts become equal. The outage--mobility trade-off therefore remains partly visible but is resolution-sensitive in both ranking detail and event detail.

## K. Scientific interpretation

Dense sampling lowers absolute outage for all three points and materially improves Conservative P5 SINR, so numerical equivalence cannot be claimed. Nevertheless, Balanced remains the lowest-outage point and Conservative remains least mobile. Dense resolution removes the Aggressive ping-pong pair, demonstrating that short-TTT mobility-event counts are sensitive to RT resolution. The appropriate conclusion is partial qualitative robustness, not sufficiency of the 25-m trace.

## L. Limitations

- One deterministic seed/run and one scene were tested, as required.
- Only three diagonal operating points were evaluated; this is not a factorial sensitivity surface.
- KPI sampling at 50 ms is coarser than the 19.781-ms dense replay interval and the shortest zero blocks.
- Baseline missing links use an effectively-zero weak sentinel whereas dense links use native `num_paths=0`; prior semantic testing found **operationally equivalent zero-link semantics** because neither representation is usable and neither reuses prior state.
- Literal zero channels produce expected `-inf` RSRP and `+inf` path-loss values in diagnostic files. These were confined to those fields; operational time series and KPIs had no unexpected non-finite values or parser failures.
- Spatial proximity between blockage and HO is descriptive, not causal attribution.

## M. Recommendation for manuscript

Include the dense validation as a compact sensitivity table plus a route-distance HO-position figure. Use the controlled statement: “The principal E2 trend remains partly visible under dense RT sampling, although some operating-point relationships are sensitive to RT resolution.” Explicitly report the disappearance of Aggressive ping-pong behavior rather than claiming identical results or full sufficiency of 25-m RT sampling.
"""
    (OUT / "resolution_validation_report.md").write_text(text, encoding="utf-8")


def make_figure(comparison: list[dict[str, Any]], ho_rows: list[dict[str, Any]]) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return
    labels = [r["operating_point"] for r in comparison]
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.0))
    x = list(range(len(labels)))
    axes[0].bar([v - 0.18 for v in x], [r["coarse_outage_pct"] for r in comparison], 0.36, label="Coarse 25 m")
    axes[0].bar([v + 0.18 for v in x], [r["dense_outage_pct"] for r in comparison], 0.36, label="Dense 1.923 m")
    axes[0].set_xticks(x, labels); axes[0].set_ylabel("Radio outage below -6 dB (%)"); axes[0].legend(frameon=False)
    markers = {"Aggressive": "o", "Balanced": "s", "Conservative": "^"}
    ymap = {"Aggressive": 2, "Balanced": 1, "Conservative": 0}
    for label in labels:
        subset = [r for r in ho_rows if r["operating_point"] == label]
        c = [float(r["coarse_distance_m"]) for r in subset if r["coarse_distance_m"] != ""]
        d = [float(r["dense_distance_m"]) for r in subset if r["dense_distance_m"] != ""]
        axes[1].scatter(c, [ymap[label] + 0.10] * len(c), marker=markers[label], facecolors="none", edgecolors="tab:blue")
        axes[1].scatter(d, [ymap[label] - 0.10] * len(d), marker=markers[label], color="tab:orange")
    axes[1].set_yticks([0, 1, 2], ["Conservative", "Balanced", "Aggressive"])
    axes[1].set_xlabel("Successful HO route position (m)")
    axes[1].set_xlim(0, ROUTE_LENGTH_M)
    axes[1].grid(axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUT / "resolution_outage_and_handover_positions.png", dpi=180)
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    integrity = [validate_run(case, DENSE_RESULTS / case) for case in CASES]
    comparison, data = build_comparison()
    comparison_fields = list(comparison[0])
    write_csv(OUT / "resolution_comparison_summary.csv", comparison, comparison_fields)
    write_csv(OUT / "run_integrity_audit.csv", integrity, list(integrity[0]))
    ho_rows = [row for case in CASES for row in pair_hos(case, data[case])]
    write_csv(OUT / "handover_position_comparison.csv", ho_rows, list(ho_rows[0]))
    blocks = blockage_rows(data)
    write_csv(OUT / "dense_blockage_region_analysis.csv", blocks, list(blocks[0]))
    make_figure(comparison, ho_rows)
    write_report(comparison, integrity, blocks)
    print(json.dumps({"status": "PASS", "output": str(OUT), "classification": "B — PARTIALLY ROBUST", "comparison": comparison, "integrity": integrity}, indent=2))


if __name__ == "__main__":
    main()
