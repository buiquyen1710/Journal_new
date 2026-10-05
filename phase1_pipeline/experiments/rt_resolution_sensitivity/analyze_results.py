from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parent
MODES = ("aggressive", "balanced", "conservative")
EXPECTED_A3 = {
    "aggressive": (1.0, 40.0),
    "balanced": (3.0, 160.0),
    "conservative": (5.0, 320.0),
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_completed_case(case: Path, scene: str, spacing: int, mode: str) -> tuple[dict, dict]:
    """Return KPI/metadata only after independently verifying completion."""
    exit_path = case / "exit_code.txt"
    metadata_path = case / "case_metadata.json"
    kpi_path = case / "kpi.json"
    if not exit_path.exists() or exit_path.read_text(encoding="utf-8").strip() != "0":
        raise ValueError(f"{case}: kpi.json exists without a successful exit_code.txt")
    if not metadata_path.exists():
        raise ValueError(f"{case}: kpi.json exists without case_metadata.json")
    metadata = read_json(metadata_path)
    kpi = read_json(kpi_path)
    hom, ttt = EXPECTED_A3[mode]
    controls_ok = (
        metadata.get("case_id") == f"{scene}_{spacing}m_{mode}"
        and metadata.get("scene") == scene
        and int(metadata.get("resolution_m", -1)) == spacing
        and metadata.get("mode") == mode
        and metadata.get("exit_code") == 0
        and float(metadata.get("hom_db", math.nan)) == hom
        and float(metadata.get("ttt_ms", math.nan)) == ttt
        and float(metadata.get("train_speed_kmh", math.nan)) == 350.0
        and float(metadata.get("measurement_controller_polling_ms", math.nan)) == 50.0
        and int(metadata.get("rng_seed", -1)) == 1
        and int(metadata.get("rng_run", -1)) == 1
        and float(kpi.get("hom_db", math.nan)) == hom
        and float(kpi.get("ttt_ms", math.nan)) == ttt
        and float(kpi.get("measurement_interval_ms", math.nan)) == 50.0
        and int(kpi.get("seed", -1)) == 1
        and int(kpi.get("rng_run", -1)) == 1
    )
    if not controls_ok:
        raise ValueError(f"{case}: case identity or fixed scientific controls do not match the matrix")
    hashes = metadata.get("output_file_hashes", {})
    if not hashes or not all((case / relative).exists() and sha256(case / relative) == expected for relative, expected in hashes.items()):
        raise ValueError(f"{case}: output inventory is missing or fails SHA-256 verification")
    if "kpi.json" not in hashes or hashes["kpi.json"] != sha256(kpi_path):
        raise ValueError(f"{case}: kpi.json is absent from the verified output inventory")
    return kpi, metadata


def collect_raw() -> list[dict]:
    rows = []
    for scene in ("E2", "E6"):
        for spacing in (25, 5, 2):
            case_manifest_path = ROOT / "sionna" / scene / f"{spacing}m" / "case_manifest.json"
            if not case_manifest_path.exists():
                continue
            manifest = read_json(case_manifest_path)
            for mode in MODES:
                kpi_path = ROOT / "ns3" / scene / f"{spacing}m" / mode / "kpi.json"
                if not kpi_path.exists():
                    continue
                case = kpi_path.parent
                kpi, metadata = require_completed_case(case, scene, spacing, mode)
                if manifest.get("output_file_hashes") != metadata.get("sionna_output_file_hashes"):
                    raise ValueError(f"{case}: ns-3 provenance does not match the finalized Sionna output inventory")
                rows.append({
                    "scene": scene, "scene_class": manifest["scene_class"],
                    "route_length_km": kpi["route_length_km"], "resolution_m": spacing,
                    "rt_interval_ms": kpi["rt_interval_ms"], "measurement_interval_ms": kpi.get("measurement_interval_ms"),
                    "a3_mode": mode, "hom_db": kpi["hom_db"], "ttt_ms": kpi["ttt_ms"],
                    "mean_sinr_db": kpi["mean_sinr_db"], "p5_sinr_db": kpi["p5_sinr_db"],
                    "radio_outage_ratio_pct": kpi["radio_outage_ratio_pct"],
                    "handover_count": kpi["handover_count"], "pingpong_count": kpi["pingpong_count"],
                    "handover_per_km": kpi["handover_per_km"], "pingpong_per_km": kpi["pingpong_per_km"],
                    "num_rt_snapshots": manifest["trajectory_sample_count"], "num_valid_snapshots": kpi["num_valid_snapshots"],
                    "seed": kpi["seed"], "config_hash": manifest["config_hash"], "trace_hash": kpi["trace_hash"],
                    "runtime_s": kpi["runtime_s"],
                })
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Clear stale generated output so an earlier partial run cannot masquerade
        # as current evidence. Source/baseline files are never passed here.
        path.write_text("", encoding="utf-8")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def summarize(rows: list[dict]) -> list[dict]:
    indexed = {(r["scene"], r["a3_mode"], int(r["resolution_m"])): r for r in rows}
    result = []
    for scene in ("E2", "E6"):
        for mode in MODES:
            fine = indexed.get((scene, mode, 2))
            if not fine:
                continue
            row = {"scene": scene, "a3_mode": mode}
            for spacing in (25, 5):
                coarse = indexed.get((scene, mode, spacing))
                if not coarse:
                    continue
                outage_delta = coarse["radio_outage_ratio_pct"] - fine["radio_outage_ratio_pct"]
                row[f"delta_outage_{spacing}m_vs_2m_pct_points"] = outage_delta
                denominator = fine["radio_outage_ratio_pct"]
                row[f"relative_outage_error_{spacing}m_vs_2m_pct"] = None if abs(denominator) < 1e-9 else outage_delta / denominator * 100.0
                row[f"delta_ho_{spacing}m_vs_2m"] = coarse["handover_count"] - fine["handover_count"]
                row[f"delta_pp_{spacing}m_vs_2m"] = coarse["pingpong_count"] - fine["pingpong_count"]
            coarse25 = indexed.get((scene, mode, 25))
            middle5 = indexed.get((scene, mode, 5))
            if coarse25 and middle5:
                row["delta_outage_25m_vs_5m_pct_points"] = coarse25["radio_outage_ratio_pct"] - middle5["radio_outage_ratio_pct"]
                row["delta_ho_25m_vs_5m"] = coarse25["handover_count"] - middle5["handover_count"]
                row["delta_pp_25m_vs_5m"] = coarse25["pingpong_count"] - middle5["pingpong_count"]
                row["outage_step_magnitude_decreases_at_5m_to_2m"] = (
                    abs(middle5["radio_outage_ratio_pct"] - fine["radio_outage_ratio_pct"])
                    <= abs(coarse25["radio_outage_ratio_pct"] - middle5["radio_outage_ratio_pct"])
                )
            result.append(row)
    return result


def rankings(rows: list[dict]) -> list[dict]:
    def rank(subset: list[dict], field: str) -> str:
        groups: dict[float, list[str]] = {}
        for row in subset:
            groups.setdefault(float(row[field]), []).append(row["a3_mode"])
        return ">".join("=".join(sorted(groups[value])) for value in sorted(groups))

    result = []
    for scene in ("E2", "E6"):
        for spacing in (25, 5, 2):
            subset = [row for row in rows if row["scene"] == scene and int(row["resolution_m"]) == spacing]
            if len(subset) != 3:
                continue
            result.append({
                "scene": scene, "resolution_m": spacing,
                "outage_best_to_worst": rank(subset, "radio_outage_ratio_pct"),
                "handover_low_to_high": rank(subset, "handover_per_km"),
                "pingpong_low_to_high": rank(subset, "pingpong_per_km"),
            })
    return result


def require_completed_events(path: Path, scene: str, spacing: int, mode: str, expected_count: int) -> list[dict[str, str]]:
    required_columns = {
        "scene", "resolution_m", "operating_point", "event_index",
        "handover_start_time_s", "handover_end_time_s", "source_gnb", "target_gnb",
        "train_position_m", "train_x", "train_y", "SINR_before", "SINR_after",
        "event_source", "start_event_join", "context_join",
    }
    if not path.exists():
        raise ValueError(f"{path}: verified KPI case lacks handover_events.csv")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not required_columns <= set(reader.fieldnames or []):
            raise ValueError(f"{path}: incomplete event schema")
        raw_events = list(reader)
    if len(raw_events) != expected_count:
        raise ValueError(f"{path}: {len(raw_events)} events do not match KPI handover_count={expected_count}")
    for expected_index, raw in enumerate(raw_events, start=1):
        missing = [column for column in ("event_index", "handover_end_time_s", "source_gnb", "target_gnb") if not raw.get(column)]
        if missing:
            raise ValueError(f"{path} lacks required completed-HO fields: {missing}")
        identity_ok = (
            raw.get("scene") == scene
            and raw.get("resolution_m") == str(spacing)
            and raw.get("operating_point") == mode
            and int(raw["event_index"]) == expected_index
        )
        start = numeric(raw.get("handover_start_time_s"))
        end = numeric(raw.get("handover_end_time_s"))
        start_join = raw.get("start_event_join")
        event_semantics_ok = (
            raw.get("event_source") == "NrGnbRrc/HandoverEndOk"
            and start_join in {"exact IMSI/source/target/time match", "unavailable: no exact start match"}
            and end is not None
            and (start_join != "exact IMSI/source/target/time match" or (start is not None and start <= end))
        )
        if not identity_ok or not event_semantics_ok:
            raise ValueError(f"{path}: invalid completed-HO identity, ordering or event source at row {expected_index}")
    return raw_events


def collect_events(
    valid_cases: set[tuple[str, int, str]] | None = None,
    expected_handover_counts: dict[tuple[str, int, str], int] | None = None,
) -> list[dict]:
    events: list[dict] = []
    for scene in ("E2", "E6"):
        for spacing in (25, 5, 2):
            for mode in MODES:
                key = (scene, spacing, mode)
                if valid_cases is not None and key not in valid_cases:
                    continue
                path = ROOT / "ns3" / scene / f"{spacing}m" / mode / "handover_events.csv"
                expected_count = expected_handover_counts.get(key, 0) if expected_handover_counts is not None else 0
                raw_events = require_completed_events(path, scene, spacing, mode, expected_count)
                for raw in raw_events:
                    events.append({
                        "scene": scene, "resolution_m": spacing, "operating_point": mode,
                        "event_index": raw["event_index"],
                        "handover_start_time_s": raw.get("handover_start_time_s") or "unavailable",
                        "handover_end_time_s": raw["handover_end_time_s"],
                        "source_gnb": raw["source_gnb"], "target_gnb": raw["target_gnb"],
                        "train_position_m": raw.get("train_position_m") or "unavailable",
                        "train_x": raw.get("train_x") or "unavailable", "train_y": raw.get("train_y") or "unavailable",
                        "SINR_before": raw.get("SINR_before") or "unavailable", "SINR_after": raw.get("SINR_after") or "unavailable",
                        "start_event_join": raw.get("start_event_join") or "unavailable",
                        "context_join": raw.get("context_join") or "unavailable",
                    })
    return events


def numeric(value: object) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def lcs_pairs(left: list[dict], right: list[dict]) -> list[tuple[int, int]]:
    """Exact source->target LCS; it never matches different handover transitions."""
    n, m = len(left), len(right)
    table = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            same = (left[i]["source_gnb"], left[i]["target_gnb"]) == (right[j]["source_gnb"], right[j]["target_gnb"])
            table[i][j] = 1 + table[i + 1][j + 1] if same else max(table[i + 1][j], table[i][j + 1])
    pairs = []
    i = j = 0
    while i < n and j < m:
        same = (left[i]["source_gnb"], left[i]["target_gnb"]) == (right[j]["source_gnb"], right[j]["target_gnb"])
        if same:
            pairs.append((i, j)); i += 1; j += 1
        elif table[i + 1][j] >= table[i][j + 1]:
            i += 1
        else:
            j += 1
    return pairs


def scientifically_valid_pairs(left: list[dict], right: list[dict]) -> tuple[list[tuple[int, int]], int, str]:
    """Match exact directed transitions without assigning ambiguous repeats.

    Identical sequences have an unambiguous index-to-index correspondence. If
    sequences differ, an LCS is used only as an ordering constraint and a pair
    is retained only when its directed transition occurs once in each sequence.
    This prevents repeated A->B transitions from being force-matched to the
    wrong physical event merely because they share the same cell IDs.
    """
    left_transitions = [(event["source_gnb"], event["target_gnb"]) for event in left]
    right_transitions = [(event["source_gnb"], event["target_gnb"]) for event in right]
    if left_transitions == right_transitions:
        return list(zip(range(len(left)), range(len(right)))), 0, "identical sequence; index-to-index"
    left_counts, right_counts = Counter(left_transitions), Counter(right_transitions)
    ordered_pairs = lcs_pairs(left, right)
    pairs = [
        (left_index, right_index)
        for left_index, right_index in ordered_pairs
        if left_counts[left_transitions[left_index]] == 1 and right_counts[right_transitions[right_index]] == 1
    ]
    return pairs, len(ordered_pairs) - len(pairs), "ordered unique-transition anchors; ambiguous repeats excluded"


def event_alignment(events: list[dict], kpi_rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, int, str], list[dict]] = {}
    for event in events:
        grouped.setdefault((event["scene"], int(event["resolution_m"]), event["operating_point"]), []).append(event)
    for value in grouped.values():
        value.sort(key=lambda item: int(item["event_index"]))
    output = []
    available = {(row["scene"], int(row["resolution_m"]), row["a3_mode"]) for row in kpi_rows}
    for scene in ("E2", "E6"):
        for mode in MODES:
            reference = grouped.get((scene, 2, mode), [])
            for spacing in (25, 5):
                if (scene, spacing, mode) not in available or (scene, 2, mode) not in available:
                    continue
                candidate = grouped.get((scene, spacing, mode), [])
                pairs, ambiguous_pairs, alignment_method = scientifically_valid_pairs(candidate, reference)
                start_time_shifts = []
                end_time_shifts = []
                position_shifts = []
                for left_index, right_index in pairs:
                    left, right = candidate[left_index], reference[right_index]
                    left_start, right_start = numeric(left["handover_start_time_s"]), numeric(right["handover_start_time_s"])
                    left_end, right_end = numeric(left["handover_end_time_s"]), numeric(right["handover_end_time_s"])
                    left_pos, right_pos = numeric(left["train_position_m"]), numeric(right["train_position_m"])
                    if left_start is not None and right_start is not None:
                        start_time_shifts.append(abs(left_start - right_start) * 1000.0)
                    if left_end is not None and right_end is not None:
                        end_time_shifts.append(abs(left_end - right_end) * 1000.0)
                    if left_pos is not None and right_pos is not None:
                        position_shifts.append(abs(left_pos - right_pos))
                output.append({
                    "scene": scene, "operating_point": mode, "comparison": f"{spacing}m_vs_2m",
                    "sequence_identical": [
                        (event["source_gnb"], event["target_gnb"]) for event in candidate
                    ] == [
                        (event["source_gnb"], event["target_gnb"]) for event in reference
                    ],
                    "alignment_method": alignment_method,
                    "ambiguous_repeated_transition_pairs_excluded": ambiguous_pairs,
                    "matched_events": len(pairs), "unmatched_candidate_events": len(candidate) - len(pairs),
                    "unmatched_reference_events": len(reference) - len(pairs),
                    "extra_events": len(candidate) - len(pairs),
                    "missing_events": len(reference) - len(pairs),
                    "mean_abs_HO_start_time_shift_ms": mean(start_time_shifts) if start_time_shifts else None,
                    "median_abs_HO_start_time_shift_ms": median(start_time_shifts) if start_time_shifts else None,
                    "max_abs_HO_start_time_shift_ms": max(start_time_shifts) if start_time_shifts else None,
                    "mean_abs_HO_end_time_shift_ms": mean(end_time_shifts) if end_time_shifts else None,
                    "median_abs_HO_end_time_shift_ms": median(end_time_shifts) if end_time_shifts else None,
                    "max_abs_HO_end_time_shift_ms": max(end_time_shifts) if end_time_shifts else None,
                    "mean_abs_HO_position_shift_m": mean(position_shifts) if position_shifts else None,
                    "median_abs_HO_position_shift_m": median(position_shifts) if position_shifts else None,
                    "max_abs_HO_position_shift_m": max(position_shifts) if position_shifts else None,
                })
    return output


def make_table(rows: list[dict]) -> None:
    indexed = {(r["scene"], r["a3_mode"], int(r["resolution_m"])): r for r in rows}
    compact = []
    for scene in ("E2", "E6"):
        for mode in MODES:
            if not all((scene, mode, spacing) in indexed for spacing in (25, 5, 2)):
                continue
            row = {"Scene": scene, "A3 mode": mode}
            for spacing in (25, 5, 2):
                row[f"Outage {spacing}m"] = indexed[(scene, mode, spacing)]["radio_outage_ratio_pct"]
            for spacing in (25, 5, 2):
                source = indexed[(scene, mode, spacing)]
                row[f"HO {spacing}m"] = source["handover_count"]
            for spacing in (25, 5, 2):
                source = indexed[(scene, mode, spacing)]
                row[f"PP {spacing}m"] = source["pingpong_count"]
            compact.append(row)
    write_csv(ROOT / "tables" / "table_temporal_resolution_sensitivity.csv", compact)
    if not compact:
        return
    columns = list(compact[0])
    lines = ["\\begin{tabular}{ll" + "rrr" * 3 + "}", "\\toprule",
             "Scene & A3 mode & \\multicolumn{3}{c}{Outage (\\%)} & \\multicolumn{3}{c}{HO} & \\multicolumn{3}{c}{PP} \\\\",
             " & & 25 m & 5 m & 2 m & 25 m & 5 m & 2 m & 25 m & 5 m & 2 m \\\\", "\\midrule"]
    for row in compact:
        values = [f"{float(row[f'Outage {spacing}m']):.3f}" for spacing in (25, 5, 2)]
        values.extend(str(int(row[f"HO {spacing}m"])) for spacing in (25, 5, 2))
        values.extend(str(int(row[f"PP {spacing}m"])) for spacing in (25, 5, 2))
        lines.append(f"{row['Scene']} & {row['A3 mode']} & " + " & ".join(values) + " \\\\")
    lines.extend(["\\bottomrule", "\\end{tabular}", ""])
    (ROOT / "tables" / "table_temporal_resolution_sensitivity.tex").write_text("\n".join(lines), encoding="utf-8")


def make_figures(rows: list[dict]) -> None:
    if len(rows) != 18:
        return
    import matplotlib.pyplot as plt
    (ROOT / "figures").mkdir(parents=True, exist_ok=True)
    colors = {"aggressive": "#D55E00", "balanced": "#0072B2", "conservative": "#009E73"}
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.15), sharey=False)
    for axis, scene in zip(axes, ("E2", "E6")):
        for mode in MODES:
            subset = {int(r["resolution_m"]): r for r in rows if r["scene"] == scene and r["a3_mode"] == mode}
            x = [25, 5, 2]
            axis.plot(x, [subset[v]["radio_outage_ratio_pct"] for v in x], marker="o", label=mode.capitalize(), color=colors[mode])
        axis.set_title(scene); axis.set_xlabel("RT spatial interval (m)"); axis.grid(True, alpha=.25); axis.invert_xaxis()
    axes[0].set_ylabel("Radio-outage ratio (%)")
    axes[1].legend(frameon=False, fontsize=8)
    fig.tight_layout()
    for suffix, dpi in (("pdf", 300), ("png", 360)):
        fig.savefig(ROOT / "figures" / f"fig_resolution_outage.{suffix}", dpi=dpi, bbox_inches="tight")
    plt.close(fig)

    for metric, ylabel, stem in (
        ("handover_per_km", "Successful handovers per km", "fig_resolution_handover_density"),
        ("pingpong_per_km", "Ping-pong events per km", "fig_resolution_pingpong_density"),
    ):
        fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.15), sharey=False)
        for axis, scene in zip(axes, ("E2", "E6")):
            for mode in MODES:
                subset = {int(r["resolution_m"]): r for r in rows if r["scene"] == scene and r["a3_mode"] == mode}
                x = [25, 5, 2]
                axis.plot(x, [subset[v][metric] for v in x], marker="o", label=mode.capitalize(), color=colors[mode])
            axis.set_title(scene); axis.set_xlabel("RT spatial interval (m)"); axis.grid(True, alpha=.25); axis.invert_xaxis()
        axes[0].set_ylabel(ylabel)
        axes[1].legend(frameon=False, fontsize=8)
        fig.tight_layout()
        for suffix, dpi in (("pdf", 300), ("png", 360)):
            fig.savefig(ROOT / "figures" / f"{stem}.{suffix}", dpi=dpi, bbox_inches="tight")
        plt.close(fig)


RANKING_FIELDS = (
    "outage_best_to_worst",
    "handover_low_to_high",
    "pingpong_low_to_high",
)


def ranking_preservation(ranking_rows: list[dict]) -> dict[str, tuple[int, int]]:
    indexed = {(r["scene"], int(r["resolution_m"])): r for r in ranking_rows}
    counts = {field: [0, 0] for field in RANKING_FIELDS}
    for scene in ("E2", "E6"):
        reference = indexed.get((scene, 2))
        if not reference:
            continue
        for spacing in (25, 5):
            candidate = indexed.get((scene, spacing))
            if candidate:
                for field in RANKING_FIELDS:
                    counts[field][1] += 1
                    counts[field][0] += candidate[field] == reference[field]
    return {field: (value[0], value[1]) for field, value in counts.items()}


def uniformly_best_modes(rows: list[dict], spacing: int) -> set[str]:
    """Modes tied for minimum outage, HO/km and PP/km in both scenes."""
    best_sets: list[set[str]] = []
    for scene in ("E2", "E6"):
        candidates = [row for row in rows if row["scene"] == scene and int(row["resolution_m"]) == spacing]
        if len(candidates) != 3:
            return set()
        for field in ("radio_outage_ratio_pct", "handover_per_km", "pingpong_per_km"):
            best_value = min(float(row[field]) for row in candidates)
            best_sets.append({row["a3_mode"] for row in candidates if float(row[field]) == best_value})
    return set.intersection(*best_sets) if best_sets else set()


def interpretation(rows: list[dict], summary: list[dict], ranking_rows: list[dict], alignment_rows: list[dict]) -> str:
    if not rows:
        return "# Result interpretation\n\nNo ns-3 KPI files have been ingested. No robustness conclusion is made.\n"
    if len(rows) != 18:
        return f"# Result interpretation\n\nOnly {len(rows)}/18 main ns-3 cases have been ingested. No robustness classification or paper conclusion is made.\n"
    outage_changes = [abs(value) for row in summary for key, value in row.items() if key in {"delta_outage_25m_vs_2m_pct_points", "delta_outage_5m_vs_2m_pct_points"} and value is not None]
    ho_changes = [abs(value) for row in summary for key, value in row.items() if key in {"delta_ho_25m_vs_2m", "delta_ho_5m_vs_2m"} and value is not None]
    pp_changes = [abs(value) for row in summary for key, value in row.items() if key in {"delta_pp_25m_vs_2m", "delta_pp_5m_vs_2m"} and value is not None]
    preservation = ranking_preservation(ranking_rows)
    outage_preserved, outage_total = preservation["outage_best_to_worst"]
    ho_rank_preserved, ho_rank_total = preservation["handover_low_to_high"]
    pp_rank_preserved, pp_rank_total = preservation["pingpong_low_to_high"]
    preserved = outage_preserved + ho_rank_preserved + pp_rank_preserved
    total = outage_total + ho_rank_total + pp_rank_total
    uniform_best_2m = uniformly_best_modes(rows, 2)
    global_claim_supported = not uniform_best_2m
    sequence_preserved = sum(bool(row["sequence_identical"]) for row in alignment_rows)
    convergence_count = sum(bool(row.get("outage_step_magnitude_decreases_at_5m_to_2m")) for row in summary)
    matched_events = sum(int(row["matched_events"]) for row in alignment_rows)
    extra_events = sum(int(row["extra_events"]) for row in alignment_rows)
    missing_events = sum(int(row["missing_events"]) for row in alignment_rows)
    ambiguous_pairs = sum(int(row["ambiguous_repeated_transition_pairs_excluded"]) for row in alignment_rows)
    max_start_shift = max((float(row["max_abs_HO_start_time_shift_ms"]) for row in alignment_rows if numeric(row.get("max_abs_HO_start_time_shift_ms")) is not None), default=None)
    max_end_shift = max((float(row["max_abs_HO_end_time_shift_ms"]) for row in alignment_rows if numeric(row.get("max_abs_HO_end_time_shift_ms")) is not None), default=None)
    max_position_shift = max((float(row["max_abs_HO_position_shift_m"]) for row in alignment_rows if numeric(row.get("max_abs_HO_position_shift_m")) is not None), default=None)
    exact_kpi_invariance = all(value == 0 for value in outage_changes + ho_changes + pp_changes)
    classification = ("Case C — resolution-sensitive" if (total and preserved < total) or not global_claim_supported else
                      "Case A — strong robustness" if exact_kpi_invariance and total and preserved == total else
                      "Case B — qualitative robustness")
    conclusion = ("The 25-m native sampling materially affects at least one operating-point ranking or the fine-grid cross-site conclusion; finer RT sampling is required."
                  if classification.startswith("Case C") else
                  "Fine-resolution replay may change absolute KPI values, but all evaluated outage and mobility-activity rankings are preserved and no operating point is uniformly best at 2 m.")
    return "\n".join([
        "# Result interpretation", "",
        f"- Classification: **{classification}**",
        f"- Maximum absolute outage change: {max(outage_changes):.6g} percentage points",
        f"- Median absolute outage change: {median(outage_changes):.6g} percentage points",
        f"- Maximum HO-count change: {max(ho_changes):.6g}",
        f"- Maximum PP-count change: {max(pp_changes):.6g}",
        f"- All outage/HO/PP ranking comparisons preserved: {preserved}/{total} ({100.0 * preserved / total:.1f}%)",
        f"- Outage-ranking comparisons preserved: {outage_preserved}/{outage_total}",
        f"- HO-density ranking comparisons preserved: {ho_rank_preserved}/{ho_rank_total}",
        f"- PP-density ranking comparisons preserved: {pp_rank_preserved}/{pp_rank_total}",
        f"- Cross-site no-uniformly-preferable operating-point claim at 2 m: {'supported' if global_claim_supported else 'not supported'}",
        f"- Uniformly best modes at 2 m under outage/HO-density/PP-density minima: {','.join(sorted(uniform_best_2m)) if uniform_best_2m else 'none'}",
        f"- Identical completed-HO event sequences: {sequence_preserved}/{len(alignment_rows)}", "",
        f"- Matched/extra/missing completed-HO events: {matched_events}/{extra_events}/{missing_events}",
        f"- Ambiguous repeated-transition pairs excluded from shift statistics: {ambiguous_pairs}",
        f"- Maximum matched-event start/end/position shift: {max_start_shift if max_start_shift is not None else 'unavailable'} ms / {max_end_shift if max_end_shift is not None else 'unavailable'} ms / {max_position_shift if max_position_shift is not None else 'unavailable'} m", "",
        f"- Outage step magnitude decreased from 25→5 m to 5→2 m: {convergence_count}/{len(summary)} operating points", "",
        conclusion, "",
        "No numerical small-change threshold is imposed; the absolute changes above are reported directly.", "",
    ])


def paper_outputs(rows: list[dict], summary: list[dict], ranking_rows: list[dict], alignment_rows: list[dict]) -> None:
    """Write result-dependent prose only after all 18 real cases are available."""
    if len(rows) != 18:
        return
    outage_changes = [abs(value) for row in summary for key, value in row.items() if key in {"delta_outage_25m_vs_2m_pct_points", "delta_outage_5m_vs_2m_pct_points"} and value is not None]
    ho_changes = [abs(value) for row in summary for key, value in row.items() if key in {"delta_ho_25m_vs_2m", "delta_ho_5m_vs_2m"} and value is not None]
    pp_changes = [abs(value) for row in summary for key, value in row.items() if key in {"delta_pp_25m_vs_2m", "delta_pp_5m_vs_2m"} and value is not None]
    preservation = ranking_preservation(ranking_rows)
    outage_preserved, outage_total = preservation["outage_best_to_worst"]
    ho_rank_preserved, ho_rank_total = preservation["handover_low_to_high"]
    pp_rank_preserved, pp_rank_total = preservation["pingpong_low_to_high"]
    preserved = outage_preserved + ho_rank_preserved + pp_rank_preserved
    total = outage_total + ho_rank_total + pp_rank_total
    uniform_best_2m = uniformly_best_modes(rows, 2)
    global_claim_supported = not uniform_best_2m
    sequence_preserved = sum(bool(row["sequence_identical"]) for row in alignment_rows)
    convergence_count = sum(bool(row.get("outage_step_magnitude_decreases_at_5m_to_2m")) for row in summary)
    matched_events = sum(int(row["matched_events"]) for row in alignment_rows)
    extra_events = sum(int(row["extra_events"]) for row in alignment_rows)
    missing_events = sum(int(row["missing_events"]) for row in alignment_rows)
    ambiguous_pairs = sum(int(row["ambiguous_repeated_transition_pairs_excluded"]) for row in alignment_rows)
    max_start_shift = max((float(row["max_abs_HO_start_time_shift_ms"]) for row in alignment_rows if numeric(row.get("max_abs_HO_start_time_shift_ms")) is not None), default=None)
    max_end_shift = max((float(row["max_abs_HO_end_time_shift_ms"]) for row in alignment_rows if numeric(row.get("max_abs_HO_end_time_shift_ms")) is not None), default=None)
    max_position_shift = max((float(row["max_abs_HO_position_shift_m"]) for row in alignment_rows if numeric(row.get("max_abs_HO_position_shift_m")) is not None), default=None)
    sensitive = preserved < total or not global_claim_supported
    exact_kpi_invariance = all(value == 0 for value in outage_changes + ho_changes + pp_changes)
    indexed = {(r["scene"], r["a3_mode"], int(r["resolution_m"])): r for r in rows}
    best = {}
    for scene in ("E2", "E6"):
        for spacing in (25, 5, 2):
            candidates = [indexed[(scene, mode, spacing)] for mode in MODES]
            value = min(row["radio_outage_ratio_pct"] for row in candidates)
            best[(scene, spacing)] = {
                "modes": "=".join(sorted(row["a3_mode"] for row in candidates if row["radio_outage_ratio_pct"] == value)),
                "value": value,
            }
    rank_index = {(row["scene"], int(row["resolution_m"])): row["outage_best_to_worst"] for row in ranking_rows}
    rank_text = "; ".join(
        f"{scene}: 25 m {rank_index[(scene, 25)]}, 5 m {rank_index[(scene, 5)]}, and 2 m {rank_index[(scene, 2)]}"
        for scene in ("E2", "E6")
    )
    baseline_reconciliation = (
        "The isolated E6 25-m row is not a reproduction of the earlier paper-side E6 timing metadata: "
        "the paper-side route/duration were 7891.768 m/81.1725 s, whereas the distance/speed-consistent "
        "isolated route/duration are 7911.427 m/81.3747 s. Although coordinates and converted channels "
        "match, this 0.249% replay-timing difference changes the 50-ms controller phase; therefore the "
        "reported 25/5/2-m trends are within-matrix sensitivity results and must not be described as "
        "reproducing the earlier E6 numerical baseline."
    )
    results = (
        "# Temporal-resolution sensitivity results\n\n"
        f"The complete 18-case sensitivity matrix produced a maximum absolute outage change of "
        f"{max(outage_changes):.3f} percentage points and a median change of {median(outage_changes):.3f} "
        f"percentage points relative to the 2-m reference. The maximum changes in completed handover "
        f"and ping-pong counts were {max(ho_changes):g} and {max(pp_changes):g}, respectively. "
        f"Outage ordering was preserved in {outage_preserved}/{outage_total} coarse-to-fine comparisons; "
        f"across outage, handover-density and ping-pong-density rankings, {preserved}/{total} comparisons were preserved. "
        f"At 2 m, the cross-site no-uniformly-preferable operating-point claim was "
        f"{'supported' if global_claim_supported else 'not supported'}, with "
        f"{','.join(sorted(uniform_best_2m)) if uniform_best_2m else 'no mode'} jointly minimizing all three metrics in both scenes. "
        f"Meanwhile, "
        f"{sequence_preserved}/{len(alignment_rows)} completed-handover sequences were identical. "
        f"The absolute outage change decreased from the 25-to-5-m step to the 5-to-2-m step in "
        f"{convergence_count}/{len(summary)} scene/operating-point combinations. "
        f"At 2 m, the lowest outage was obtained by {best[('E2', 2)]['modes']} in E2 "
        f"({best[('E2', 2)]['value']:.3f}%) and by {best[('E6', 2)]['modes']} in E6 "
        f"({best[('E6', 2)]['value']:.3f}%). "
        f"The outage rankings were {rank_text}. "
        f"Event-sequence alignment matched {matched_events} completed handovers, with {extra_events} extra and {missing_events} missing events relative to the 2-m sequences. "
        f"A total of {ambiguous_pairs} repeated-transition pairs were excluded from timing/position shifts because their correspondence was not unique. "
        + (f"Across valid matches, maximum absolute start-time, end-time and position shifts were {max_start_shift:.3f} ms, {max_end_shift:.3f} ms and {max_position_shift:.3f} m. " if max_start_shift is not None and max_end_shift is not None and max_position_shift is not None else "No complete matched-event triplet was available for a joint timing/position maximum. ")
        + ("The changed ranking or fine-grid cross-site conclusion indicates material resolution sensitivity. " if sensitive else
           "Thus, refinement changed absolute values without changing the evaluated outage or mobility-activity rankings. ")
        + baseline_reconciliation + "\n"
    )
    limitations = (
        "# Revised limitations\n\n"
        + ("The native 25-m grid materially affected at least one operating-point ordering, so fine RT sampling is required for these evaluated cases. " if sensitive else
           "The main qualitative operating-point ordering was preserved in the representative E2/E6 refinement experiment, although individual KPI values and event timing remained resolution dependent. ")
        + "The 40-ms TTT remains shorter than the hard-coded 50-ms custom-controller polling cadence; therefore, the evaluated parameterizations are complete joint HOM–TTT operating points rather than isolated causal estimates of TTT. The converted SioLENA PHY trace uses uniform timestep-index replay and does not retain the original irregular timestamp vector. "
        + baseline_reconciliation + "\n"
    )
    contribution = (
        "# Revised contribution\n\n"
        + ("A temporal-resolution sensitivity analysis that identifies resolution-dependent site-specific Event-A3 behavior under substantially finer ray-tracing sampling.\n" if sensitive else
           "A temporal-resolution sensitivity analysis showing that the evaluated site-dependent Event-A3 outage ordering persists under substantially finer ray-tracing sampling in two representative scenes.\n")
    )
    conclusion = (
        "Sensitivity experiments with finer RT sampling show that at least one site-dependent operating-point trend changes with temporal resolution, motivating finer sampling for reliable evaluation.\n" if sensitive else
        "Sensitivity experiments with finer RT sampling show that the principal evaluated site-dependent operating-point ordering remains stable, while absolute KPIs and event timing retain resolution dependence.\n"
    )
    paper_dir = ROOT / "paper_ready"
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "results_temporal_resolution.md").write_text(results, encoding="utf-8")
    (paper_dir / "revised_limitations.md").write_text(limitations, encoding="utf-8")
    (paper_dir / "revised_contribution.md").write_text(contribution, encoding="utf-8")
    (paper_dir / "revised_conclusion_sentence.md").write_text(conclusion, encoding="utf-8")

    robustness_answer = "NO" if sensitive else ("YES" if exact_kpi_invariance else "PARTIALLY")
    recommendation = (
        "Use the 2-m results as the main numerical evidence and revise any ordering or cross-site claim that differs from the fine reference."
        if sensitive else
        "Retain the 25-m results as the main baseline and present the 5/2-m sensitivity evidence alongside them."
        if exact_kpi_invariance else
        "Retain the qualitative 25-m trends, use the 2-m values for fine-resolution numerical claims, and report the measured sensitivity deltas prominently."
    )
    formatted_start_shift = f"{max_start_shift:.3f}" if max_start_shift is not None else "unavailable"
    formatted_end_shift = f"{max_end_shift:.3f}" if max_end_shift is not None else "unavailable"
    formatted_position_shift = f"{max_position_shift:.3f}" if max_position_shift is not None else "unavailable"
    trajectory_path = ROOT / "analysis" / "trajectory_resolution_validation.csv"
    with trajectory_path.open(newline="", encoding="utf-8") as handle:
        trajectory_rows = list(csv.DictReader(handle))
    trajectory_index = {(row["scene"], int(float(row["requested_spacing_m"]))): row for row in trajectory_rows}
    report = [
        "# Final technical assessment", "",
        "## A. Code changed", "",
        "The isolated implementation comprises `run_experiment.py`, `prepare_ns3_package.py`, `validate_rt_traces.py`, "
        "`ns3_package/verify_handoff.py`, `ns3_package/run_resolution_matrix.py`, `analyze_results.py`, "
        "`verify_experiment.py`, `post_rt_watcher.py` and `test_ns3_parser.py`. Their roles and provenance are listed in "
        "`analysis/implementation_inventory.md`; no legacy baseline output directory is modified.", "",
        "## B. Experimental matrix actually completed", "",
    ]
    for scene in ("E2", "E6"):
        report.append(f"- {scene}: 25 m (Agg/Bal/Cons), 5 m (Agg/Bal/Cons), 2 m (Agg/Bal/Cons)")
    report.extend(["", "## C. Temporal verification", "", "| Scene | Grid | Samples | Mean spatial interval (m) | Mean temporal interval (ms) | Min–max temporal interval (ms) |", "|---|---:|---:|---:|---:|---:|"])
    for scene in ("E2", "E6"):
        for spacing in (25, 5, 2):
            row = trajectory_index[(scene, spacing)]
            report.append(
                f"| {scene} | {spacing} m | {int(float(row['number_of_samples']))} | "
                f"{float(row['actual_mean_spacing_m']):.3f} | {float(row['mean_temporal_interval_ms']):.3f} | "
                f"{float(row['min_temporal_interval_ms']):.3f}–{float(row['max_temporal_interval_ms']):.3f} |"
            )
    report.extend(["", "## D. Main KPI table", "", "| Scene | Grid | Mode | Mean SINR (dB) | P5 SINR (dB) | Outage (%) | HO | PP | HO/km | PP/km |", "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|"])
    for scene in ("E2", "E6"):
        for spacing in (25, 5, 2):
            for mode in MODES:
                row = indexed[(scene, mode, spacing)]
                report.append(
                    f"| {scene} | {spacing} m | {mode.capitalize()} | {float(row['mean_sinr_db']):.3f} | "
                    f"{float(row['p5_sinr_db']):.3f} | {float(row['radio_outage_ratio_pct']):.3f} | "
                    f"{int(row['handover_count'])} | {int(row['pingpong_count'])} | "
                    f"{float(row['handover_per_km']):.3f} | {float(row['pingpong_per_km']):.3f} |"
                )
    report.extend([
        "", "## E. Robustness conclusion", "",
        f"**Does the main paper conclusion survive RT refinement? {robustness_answer}.**",
        f"Maximum/median absolute outage changes relative to 2 m are {max(outage_changes):.3f}/{median(outage_changes):.3f} percentage points. "
        f"The maximum HO/PP count changes are {max(ho_changes):g}/{max(pp_changes):g}; {preserved}/{total} outage/HO/PP ranking comparisons are preserved. "
        f"The 2-m no-uniformly-preferable claim is {'supported' if global_claim_supported else 'not supported'}.",
        "", "## F. E2", "",
        f"Outage ranking: 25 m `{rank_index[('E2', 25)]}`; 5 m `{rank_index[('E2', 5)]}`; 2 m `{rank_index[('E2', 2)]}`.",
        "", "## G. E6", "",
        f"Outage ranking: 25 m `{rank_index[('E6', 25)]}`; 5 m `{rank_index[('E6', 5)]}`; 2 m `{rank_index[('E6', 2)]}`.",
        baseline_reconciliation,
        "", "## H. Mobility events", "",
        f"Across 25/5-m versus 2-m alignments, {matched_events} completed-HO events match, {extra_events} are extra and {missing_events} are missing. "
        f"{ambiguous_pairs} repeated-transition pairs are excluded from shift statistics because their correspondence is ambiguous. "
        f"The maximum valid start/end/position shifts are {formatted_start_shift} ms, "
        f"{formatted_end_shift} ms and {formatted_position_shift} m; "
        f"{sequence_preserved}/{len(alignment_rows)} event sequences are identical.",
        "", "## I. Measurement interval", "",
        "The audited FixedA3 controller polls at a hard-coded 50 ms. No standards-consistent independent 10/20-ms PHY/L3 measurement-cadence control exists, so no auxiliary cadence experiment is fabricated. The 40-ms TTT remains shorter than this polling interval and all settings are interpreted as joint HOM–TTT operating points.",
        "", "## J. Paper recommendation", "", recommendation, "",
    ])
    (paper_dir / "final_technical_assessment.md").write_text("\n".join(report), encoding="utf-8")


def main() -> None:
    rows = collect_raw()
    summary_rows = summarize(rows)
    ranking_rows = rankings(rows)
    valid_cases = {(row["scene"], int(row["resolution_m"]), row["a3_mode"]) for row in rows}
    expected_handover_counts = {
        (row["scene"], int(row["resolution_m"]), row["a3_mode"]): int(row["handover_count"])
        for row in rows
    }
    events = collect_events(valid_cases, expected_handover_counts)
    alignment_rows = event_alignment(events, rows)
    write_csv(ROOT / "analysis" / "all_cases_raw.csv", rows)
    write_csv(ROOT / "analysis" / "resolution_sensitivity_summary.csv", summary_rows)
    write_csv(ROOT / "analysis" / "operating_point_rankings.csv", ranking_rows)
    write_csv(ROOT / "analysis" / "handover_events.csv", events)
    write_csv(ROOT / "analysis" / "handover_event_alignment.csv", alignment_rows)
    make_table(rows)
    make_figures(rows)
    paper_outputs(rows, summary_rows, ranking_rows, alignment_rows)
    (ROOT / "paper_ready" / "result_interpretation.md").write_text(interpretation(rows, summary_rows, ranking_rows, alignment_rows), encoding="utf-8")


if __name__ == "__main__":
    main()
