from __future__ import annotations

from typing import Dict, List, Tuple


def scenario_type(config: Dict) -> str:
    return str(config.get("scenario", {}).get("type", "open_railway"))


def is_tunnel_scenario(config: Dict) -> bool:
    return scenario_type(config) == "straight_tunnel"


def is_unified_scenario(config: Dict) -> bool:
    return scenario_type(config) == "unified_3000m"


def is_external_loop_scenario(config: Dict) -> bool:
    return scenario_type(config) == "external_loop_3000m"


def active_base_station(config: Dict) -> Dict:
    if "base_station" in config:
        return config["base_station"]
    stations = config.get("base_stations", [])
    if not stations:
        raise KeyError("No base station configuration found.")
    active_index = int(config.get("simulation", {}).get("active_base_station_index", 0))
    active_index = max(0, min(active_index, len(stations) - 1))
    return stations[active_index]


def all_base_stations(config: Dict) -> List[Dict]:
    stations = []
    if "base_stations" in config:
        stations.extend(config["base_stations"])
    elif "base_station" in config:
        stations.append(config["base_station"])
    extra = config.get("portal_base_stations", [])
    for station in extra:
        if station not in stations:
            stations.append(station)
    return stations


def station_label(station: Dict, index: int) -> str:
    return str(station.get("name", f"tx{index + 1}"))


def station_output_name(station: Dict, index: int) -> str:
    default_label = f"tx{index + 1}"
    return str(station.get("output_name", default_label))


def unified_modules() -> List[Dict]:
    return [
        {"name": "module_a_viaduct", "x_start_m": 0.0, "x_end_m": 700.0, "kind": "viaduct"},
        {"name": "module_b_ground", "x_start_m": 700.0, "x_end_m": 1100.0, "kind": "ground"},
        {"name": "module_c_portal_in", "x_start_m": 1100.0, "x_end_m": 1300.0, "kind": "transition_in"},
        {"name": "module_d_tunnel", "x_start_m": 1300.0, "x_end_m": 1600.0, "kind": "tunnel"},
        {"name": "module_e_portal_out", "x_start_m": 1600.0, "x_end_m": 1900.0, "kind": "transition_out"},
        {"name": "module_f_viaduct", "x_start_m": 1900.0, "x_end_m": 3000.0, "kind": "viaduct"},
    ]


def unified_module_for_x(x_m: float) -> Dict:
    for module in unified_modules():
        if module["x_start_m"] <= x_m < module["x_end_m"]:
            return module
    return unified_modules()[-1]


def _append_trajectory_segment(
    samples: List[Tuple[float, float, float]],
    x_start_m: float,
    x_end_m: float,
    spacing_m: float,
    y_m: float,
    z_start_m: float,
    z_end_m: float,
    include_end: bool,
) -> None:
    current = float(x_start_m)
    epsilon = spacing_m / 10.0
    comparator = (lambda value: value <= x_end_m + epsilon) if include_end else (lambda value: value < x_end_m - epsilon)
    distance = max(x_end_m - x_start_m, spacing_m)
    while comparator(current):
        if samples and abs(samples[-1][0] - current) < 1e-9:
            current = round(current + spacing_m, 6)
            continue
        ratio = 0.0 if abs(x_end_m - x_start_m) < 1e-9 else (current - x_start_m) / distance
        ratio = max(0.0, min(1.0, ratio))
        z_m = z_start_m + (z_end_m - z_start_m) * ratio
        samples.append((round(current, 3), float(y_m), round(z_m, 3)))
        current = round(current + spacing_m, 6)


def unified_trajectory_samples(config: Dict) -> List[Tuple[float, float, float]]:
    trajectory_cfg = config.get("trajectory", {})
    segments = trajectory_cfg.get("segments")
    if not segments:
        raise KeyError("Unified 3000 m scenario requires trajectory.segments in the config.")
    y_default = float(trajectory_cfg.get("default_y_m", 0.0))
    samples: List[Tuple[float, float, float]] = []
    for index, segment in enumerate(segments):
        _append_trajectory_segment(
            samples=samples,
            x_start_m=float(segment["x_start_m"]),
            x_end_m=float(segment["x_end_m"]),
            spacing_m=float(segment["spacing_m"]),
            y_m=float(segment.get("y_m", y_default)),
            z_start_m=float(segment["z_start_m"]),
            z_end_m=float(segment.get("z_end_m", segment["z_start_m"])),
            include_end=bool(segment.get("include_end", index == len(segments) - 1)),
        )
    return samples
