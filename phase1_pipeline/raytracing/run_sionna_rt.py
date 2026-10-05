from __future__ import annotations

import argparse
import cmath
import json
import math
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phase1_pipeline.common import (
    SPEED_OF_LIGHT_M_S,
    add,
    dot,
    load_config,
    normalize,
    resolve_config_relative_path,
    resolve_output_paths,
    scale,
    subtract,
    vector_length,
    wavelength_m,
)
from phase1_pipeline.output.export_trace import (
    TraceCsvWriter,
    export_multi_station_validation_plots,
    export_rays_3d_visualization,
    export_rays_3d_with_mitsuba,
    export_sample_style_scene,
    export_validation_plots,
)
from phase1_pipeline.raytracing.compute_doppler import angles_from_vector, compute_doppler_hz, unit_vector_from_angles
from phase1_pipeline.scenarios import (
    active_base_station,
    all_base_stations,
    is_external_loop_scenario,
    is_tunnel_scenario,
    is_unified_scenario,
    station_label,
    station_output_name,
    unified_module_for_x,
    unified_trajectory_samples,
)


def try_import_sionna():
    try:
        ensure_drjit_llvm_path()
        import mitsuba as mi
        from sionna.rt import PathSolver, PlanarArray, Receiver, Transmitter, load_scene
    except ImportError as exc:
        print(f"Sionna RT import failed: {safe_exception_text(exc)}")
        return None
    return {
        "mi": mi,
        "PathSolver": PathSolver,
        "PlanarArray": PlanarArray,
        "Receiver": Receiver,
        "Transmitter": Transmitter,
        "load_scene": load_scene,
    }


def try_import_mitsuba():
    try:
        ensure_drjit_llvm_path()
        import mitsuba as mi
        for variant in ("scalar_rgb", "llvm_ad_rgb", "cuda_ad_rgb"):
            try:
                mi.set_variant(variant)
                break
            except Exception:
                continue
        return mi
    except ImportError:
        return None


def safe_exception_text(exc: Exception) -> str:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return str(exc).encode(encoding, errors="backslashreplace").decode(encoding, errors="replace")


def safe_path_text(path: Path) -> str:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return str(path).encode(encoding, errors="backslashreplace").decode(encoding, errors="replace")


def prepare_ascii_safe_scene(output_paths: Dict) -> Path:
    src_xml = Path(output_paths["mitsuba_xml"])
    src_mesh_dir = Path(output_paths["mesh_dir"])
    try:
        str(src_xml).encode("ascii")
        str(src_mesh_dir).encode("ascii")
        return src_xml
    except UnicodeEncodeError:
        pass
    ascii_root = Path(tempfile.gettempdir()) / "sionetrail_mitsuba_scene"
    dst_mesh_dir = ascii_root / "meshes"
    dst_mesh_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_xml, ascii_root / "scene.xml")
    if src_mesh_dir.exists():
        for mesh_file in src_mesh_dir.glob("*.obj"):
            shutil.copy2(mesh_file, dst_mesh_dir / mesh_file.name)
    return ascii_root / "scene.xml"


def ensure_drjit_llvm_path() -> None:
    if os.environ.get("DRJIT_LIBLLVM_PATH"):
        return
    candidates = [
        Path("C:/Program Files/LLVM/bin/LLVM-C.dll"),
        Path("C:/Program Files (x86)/LLVM/bin/LLVM-C.dll"),
    ]
    python_prefix = Path(sys.executable).resolve().parent
    candidates.extend(
        [
            python_prefix / "Library" / "bin" / "LLVM-C.dll",
            python_prefix / "lib" / "LLVM-C.dll",
        ]
    )
    conda_prefix = os.environ.get("CONDA_PREFIX")
    if conda_prefix:
        candidates.append(Path(conda_prefix) / "Library" / "bin" / "LLVM-C.dll")
    for candidate in candidates:
        if candidate.exists():
            os.environ["DRJIT_LIBLLVM_PATH"] = str(candidate)
            return


@dataclass
class CandidatePath:
    name: str
    points: List[Tuple[float, float, float]]
    coefficient: complex
    delay_s: float
    aoa_theta_rad: float
    aoa_phi_rad: float
    aod_theta_rad: float
    aod_phi_rad: float
    doppler_hz: float
    los_flag: int


def station_ray_origin(station: Dict) -> Tuple[float, float, float]:
    x, y, z = [float(v) for v in station["position_m"]]
    antenna_size = [float(v) for v in station.get("antenna_size_m", [0.8, 0.25, 1.2])]
    clearance = float(station.get("ray_origin_clearance_m", 0.2))
    facing = str(station.get("facing", "y-"))
    face_offset = antenna_size[1] / 2.0 + clearance
    if facing == "x+":
        x += face_offset
    elif facing == "x-":
        x -= face_offset
    elif facing == "y+":
        y += face_offset
    else:
        y -= face_offset
    return (x, y, z)


def train_velocity(config: Dict) -> Tuple[float, float, float]:
    return (float(config["simulation"]["train_speed_kmh"]) / 3.6, 0.0, 0.0)


def metadata_trajectory_samples(config: Dict) -> List[Tuple[float, Tuple[float, float, float]]]:
    output_paths = resolve_output_paths(config)
    metadata_path = output_paths["scene_metadata"]
    if not metadata_path.exists():
        raise FileNotFoundError(f"Scene metadata not found: {metadata_path}")
    with metadata_path.open("r", encoding="utf-8") as handle:
        metadata = json.load(handle)
    raw_samples = metadata.get("rx_trajectory_samples")
    if not raw_samples:
        raise KeyError(f"No rx_trajectory_samples in scene metadata: {metadata_path}")
    speed_m_s = float(config["simulation"]["train_speed_kmh"]) / 3.6
    samples: List[Tuple[float, Tuple[float, float, float]]] = []
    elapsed_distance = 0.0
    previous = None
    for raw in raw_samples:
        sample = (float(raw[0]), float(raw[1]), float(raw[2]))
        if previous is not None:
            elapsed_distance += vector_length(subtract(sample, previous))
        samples.append((elapsed_distance / speed_m_s, sample))
        previous = sample
    return samples


def external_loop_base_stations(config: Dict) -> List[Dict]:
    stations = [dict(station) for station in all_base_stations(config)]
    output_paths = resolve_output_paths(config)
    metadata_path = output_paths["scene_metadata"]
    if not metadata_path.exists():
        return stations
    with metadata_path.open("r", encoding="utf-8") as handle:
        metadata = json.load(handle)
    positions = metadata.get("all_gnb_positions_m") or []
    facings = metadata.get("all_gnb_facing") or []
    if positions:
        stations = stations[: len(positions)]
    for idx, (station, position) in enumerate(zip(stations, positions)):
        station["position_m"] = [float(position[0]), float(position[1]), float(position[2])]
        station["height_m"] = float(position[2])
        if idx < len(facings):
            station["facing"] = str(facings[idx])
    return stations


def fallback_trajectory_samples(config: Dict) -> List[Tuple[float, Tuple[float, float, float]]]:
    speed_m_s = float(config["simulation"]["train_speed_kmh"]) / 3.6
    if is_external_loop_scenario(config):
        return metadata_trajectory_samples(config)
    if is_unified_scenario(config):
        raw_samples = unified_trajectory_samples(config)
        times_and_positions = []
        elapsed_distance = 0.0
        previous = None
        for sample in raw_samples:
            if previous is not None:
                elapsed_distance += vector_length(subtract(sample, previous))
            times_and_positions.append((elapsed_distance / speed_m_s, sample))
            previous = sample
        return times_and_positions

    length = float(config["scene"]["length_m"])
    margin = float(config["simulation"].get("scene_margin_m", 15.0))
    receiver_height = float(config["train"]["receiver_height_m"])
    timestep_s = float(config["simulation"]["timestep_s"])
    start_x = -length / 2.0 + margin
    end_x = length / 2.0 - margin
    speed = float(config["simulation"]["train_speed_kmh"]) / 3.6
    duration_s = max(0.0, (end_x - start_x) / speed)
    steps = max(1, int(math.floor(duration_s / timestep_s)) + 1)
    samples = []
    for idx in range(steps):
        time_s = idx * timestep_s
        x = start_x + min(end_x - start_x, speed * time_s)
        samples.append((time_s, (x, float(config["train"].get("lateral_offset_m", 0.0)), receiver_height)))
    return samples


def complex_array_to_numpy(path_coefficients):
    if hasattr(path_coefficients, "numpy"):
        return path_coefficients.numpy()
    if isinstance(path_coefficients, (tuple, list)) and len(path_coefficients) == 2:
        return path_coefficients[0].numpy() + 1j * path_coefficients[1].numpy()
    raise TypeError(f"Unsupported Sionna path coefficient container: {type(path_coefficients)!r}")


def extract_sionna_paths(paths, config: Dict) -> List[CandidatePath]:
    import numpy as np

    coeffs = np.asarray(complex_array_to_numpy(paths.a))
    delays = np.asarray(paths.tau.numpy())
    theta_t = np.asarray(paths.theta_t.numpy())
    phi_t = np.asarray(paths.phi_t.numpy())
    theta_r = np.asarray(paths.theta_r.numpy())
    phi_r = np.asarray(paths.phi_r.numpy())
    valid = np.asarray(paths.valid.numpy())
    while coeffs.ndim > 1:
        coeffs = coeffs[0]
    while delays.ndim > 1:
        delays = delays[0]
        theta_t = theta_t[0]
        phi_t = phi_t[0]
        theta_r = theta_r[0]
        phi_r = phi_r[0]
        valid = valid[0]
    interactions = np.asarray(paths.interactions.numpy())
    if interactions.size == 0 or interactions.shape[-1] == 0:
        interaction_matrix = np.zeros((0, coeffs.shape[-1]), dtype=np.uint32)
    else:
        interaction_depth = interactions.shape[0]
        interaction_matrix = interactions.reshape(interaction_depth, -1, interactions.shape[-1])[:, 0, :]
    extracted: List[CandidatePath] = []
    velocity = train_velocity(config)
    frequency_hz = float(config["simulation"]["frequency_hz"])
    for idx in range(coeffs.shape[-1]):
        if idx >= len(valid) or not bool(valid[idx]):
            continue
        coeff = complex(coeffs[idx])
        aoa_theta = float(theta_r[idx])
        aoa_phi = float(phi_r[idx])
        arrival_from_source = unit_vector_from_angles(aoa_theta, aoa_phi)
        propagation_to_receiver = (-arrival_from_source[0], -arrival_from_source[1], -arrival_from_source[2])
        doppler = compute_doppler_hz(frequency_hz, velocity, propagation_to_receiver)
        los_flag = 1 if interaction_matrix.size == 0 or np.all(interaction_matrix[:, idx] == 0) else 0
        extracted.append(
            CandidatePath(
                name=f"sionna_{idx}",
                points=[],
                coefficient=coeff,
                delay_s=float(delays[idx]),
                aoa_theta_rad=aoa_theta,
                aoa_phi_rad=aoa_phi,
                aod_theta_rad=float(theta_t[idx]),
                aod_phi_rad=float(phi_t[idx]),
                doppler_hz=doppler,
                los_flag=los_flag,
            )
        )
    if not extracted:
        return extracted
    dynamic_range_db = float(config.get("ray_tracing", {}).get("min_relative_path_gain_db", 40.0))
    strongest = max(abs(path.coefficient) for path in extracted)
    if strongest > 0.0:
        min_magnitude = strongest * (10.0 ** (-dynamic_range_db / 20.0))
        extracted = [path for path in extracted if abs(path.coefficient) >= min_magnitude]
    extracted.sort(key=lambda path: abs(path.coefficient), reverse=True)
    max_paths_after_filter = int(config.get("ray_tracing", {}).get("max_paths_after_filter", 0) or 0)
    if max_paths_after_filter > 0:
        extracted = extracted[:max_paths_after_filter]
    return extracted


def segment_clear(scene, mi, start: Sequence[float], end: Sequence[float], epsilon: float = 1e-3) -> bool:
    direction = subtract(end, start)
    distance = vector_length(direction)
    if distance <= epsilon:
        return True
    unit_direction = normalize(direction)
    ray = mi.Ray3f(o=mi.Point3f(*start), d=mi.Vector3f(*unit_direction))
    ray.maxt = distance - epsilon
    return not bool(scene.ray_test(ray))


def polyline_clear(scene, mi, points: Sequence[Tuple[float, float, float]], epsilon: float = 1e-3) -> bool:
    for start, end in zip(points, points[1:]):
        if not segment_clear(scene, mi, start, end, epsilon=epsilon):
            return False
    return True


def reflect_point_across_plane(point, plane_point, plane_normal):
    offset = subtract(point, plane_point)
    distance = dot(offset, plane_normal)
    return subtract(point, scale(plane_normal, 2.0 * distance))


def line_plane_intersection(start, end, plane_point, plane_normal) -> Optional[Tuple[float, float, float]]:
    direction = subtract(end, start)
    denom = dot(plane_normal, direction)
    if abs(denom) < 1e-9:
        return None
    t = dot(plane_normal, subtract(plane_point, start)) / denom
    if not 0.0 < t < 1.0:
        return None
    return add(start, scale(direction, t))


def build_candidate_from_points(name: str, points, reflection_gain: complex, config: Dict, los_flag: int) -> CandidatePath:
    total_distance = 0.0
    for start, end in zip(points, points[1:]):
        total_distance += vector_length(subtract(end, start))
    wavelength = wavelength_m(float(config["simulation"]["frequency_hz"]))
    amplitude = (wavelength / (4.0 * math.pi * max(total_distance, 1e-3))) * reflection_gain
    phase = -2.0 * math.pi * total_distance / wavelength
    coefficient = amplitude * cmath.exp(1j * phase)
    aod_theta, aod_phi = angles_from_vector(subtract(points[1], points[0]))
    aoa_theta, aoa_phi = angles_from_vector(subtract(points[-2], points[-1]))
    doppler = compute_doppler_hz(float(config["simulation"]["frequency_hz"]), train_velocity(config), subtract(points[-1], points[-2]))
    return CandidatePath(
        name=name,
        points=list(points),
        coefficient=coefficient,
        delay_s=total_distance / SPEED_OF_LIGHT_M_S,
        aoa_theta_rad=aoa_theta,
        aoa_phi_rad=aoa_phi,
        aod_theta_rad=aod_theta,
        aod_phi_rad=aod_phi,
        doppler_hz=doppler,
        los_flag=los_flag,
    )


def softened_gain(base_gain: complex, validated: bool, penalty_db: float = 8.0) -> complex:
    if validated:
        return base_gain
    linear_penalty = 10.0 ** (-penalty_db / 20.0)
    return base_gain * linear_penalty


def unified_los_available(station: Dict, rx_pos: Tuple[float, float, float]) -> bool:
    name = str(station.get("name", "")).lower()
    x = rx_pos[0]
    if "tx1" in name:
        return 0.0 <= x <= 760.0
    if "tx2" in name:
        return 640.0 <= x <= 1210.0
    if "tx5" in name or "portal" in name:
        return 930.0 <= x <= 1260.0
    if "tx3" in name or "tunnel" in name:
        return 1220.0 <= x <= 1680.0
    if "tx4" in name:
        return 1700.0 <= x <= 3000.0
    return True


def unified_scatter_points(rx_pos: Tuple[float, float, float]) -> List[Tuple[float, float, float]]:
    module = unified_module_for_x(rx_pos[0])
    points: List[Tuple[float, float, float]] = []
    if module["kind"] == "viaduct":
        points.extend(
            [
                (rx_pos[0], -0.2, 17.5),
                (round(rx_pos[0] / 50.0) * 50.0, 0.0, 10.0),
            ]
        )
    elif module["kind"] in {"ground", "transition_in", "transition_out"}:
        points.extend([(rx_pos[0], -0.2, 5.5)])
        if module["kind"] == "transition_in":
            points.append((1300.0, 0.0, 4.5))
        if module["kind"] == "transition_out":
            points.append((1600.0, 0.0, 4.5))
    elif module["kind"] == "tunnel":
        points.extend([(rx_pos[0], -5.25, 4.0), (rx_pos[0], 5.25, 4.0), (rx_pos[0], 0.0, 7.5)])
    return points


def unified_surfaces(rx_pos: Tuple[float, float, float]) -> List[Dict]:
    module = unified_module_for_x(rx_pos[0])
    x = rx_pos[0]
    if module["kind"] == "viaduct":
        return [
            {"name": "deck_reflection", "point": (x, 0.0, 12.0), "normal": (0.0, 0.0, 1.0), "gain": complex(-0.45, 0.0)},
            {"name": "barrier_left", "point": (x, -3.6, 13.75), "normal": (0.0, 1.0, 0.0), "gain": complex(-0.58, 0.0)},
            {"name": "barrier_right", "point": (x, 3.6, 13.75), "normal": (0.0, -1.0, 0.0), "gain": complex(-0.58, 0.0)},
        ]
    if module["kind"] == "ground":
        return [
            {"name": "ground_reflection", "point": (x, 0.0, 0.0), "normal": (0.0, 0.0, 1.0), "gain": complex(-0.55, 0.0)},
            {"name": "barrier_left", "point": (x, -3.6, 1.75), "normal": (0.0, 1.0, 0.0), "gain": complex(-0.60, 0.0)},
            {"name": "barrier_right", "point": (x, 3.6, 1.75), "normal": (0.0, -1.0, 0.0), "gain": complex(-0.60, 0.0)},
        ]
    if module["kind"] == "transition_in":
        return [
            {"name": "ground_reflection", "point": (x, 0.0, 0.0), "normal": (0.0, 0.0, 1.0), "gain": complex(-0.55, 0.0)},
            {"name": "mountain_left", "point": (x, -5.25, 3.75), "normal": (0.0, 1.0, 0.0), "gain": complex(-0.64, 0.0)},
            {"name": "mountain_right", "point": (x, 5.25, 3.75), "normal": (0.0, -1.0, 0.0), "gain": complex(-0.64, 0.0)},
        ]
    if module["kind"] == "tunnel":
        return [
            {"name": "tunnel_floor", "point": (x, 0.0, 0.0), "normal": (0.0, 0.0, 1.0), "gain": complex(-0.50, 0.0)},
            {"name": "tunnel_ceiling", "point": (x, 0.0, 7.5), "normal": (0.0, 0.0, -1.0), "gain": complex(-0.55, 0.0)},
            {"name": "tunnel_left", "point": (x, -5.25, 3.75), "normal": (0.0, 1.0, 0.0), "gain": complex(-0.68, 0.0)},
            {"name": "tunnel_right", "point": (x, 5.25, 3.75), "normal": (0.0, -1.0, 0.0), "gain": complex(-0.68, 0.0)},
        ]
    return [
        {"name": "ground_reflection", "point": (x, 0.0, 0.0), "normal": (0.0, 0.0, 1.0), "gain": complex(-0.55, 0.0)},
        {"name": "mountain_left", "point": (x, -5.25, 3.75), "normal": (0.0, 1.0, 0.0), "gain": complex(-0.60, 0.0)},
        {"name": "mountain_right", "point": (x, 5.25, 3.75), "normal": (0.0, -1.0, 0.0), "gain": complex(-0.60, 0.0)},
    ]


def legacy_paths_for_sample(config: Dict, station: Dict, rx_pos: Tuple[float, float, float], mitsuba_scene=None, mi=None) -> List[CandidatePath]:
    tx = station_ray_origin(station)
    candidates = [build_candidate_from_points("los", [tx, rx_pos], complex(1.0, 0.0), config, 1)]
    ground_reflection = line_plane_intersection(reflect_point_across_plane(tx, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)), rx_pos, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    if ground_reflection is not None:
        clear = True if mitsuba_scene is None else polyline_clear(mitsuba_scene, mi, [tx, ground_reflection, rx_pos])
        candidates.append(build_candidate_from_points("ground_reflection", [tx, ground_reflection, rx_pos], softened_gain(complex(-0.55, 0.0), clear, 5.0), config, 0))
    if is_tunnel_scenario(config):
        for name, plane_y in (("wall_left", -5.0), ("wall_right", 5.0)):
            reflected = line_plane_intersection(reflect_point_across_plane(tx, (0.0, plane_y, 4.0), (0.0, 1.0 if plane_y < 0 else -1.0, 0.0)), rx_pos, (0.0, plane_y, 4.0), (0.0, 1.0 if plane_y < 0 else -1.0, 0.0))
            if reflected is not None:
                candidates.append(build_candidate_from_points(name, [tx, reflected, rx_pos], complex(-0.60, 0.0), config, 0))
    return sorted(candidates, key=lambda item: abs(item.coefficient), reverse=True)


def unified_paths_for_sample(config: Dict, station: Dict, rx_pos: Tuple[float, float, float], mitsuba_scene=None, mi=None) -> List[CandidatePath]:
    tx = station_ray_origin(station)
    candidates: List[CandidatePath] = []
    if unified_los_available(station, rx_pos):
        los_clear = True if mitsuba_scene is None else polyline_clear(mitsuba_scene, mi, [tx, rx_pos])
        candidates.append(build_candidate_from_points("los", [tx, rx_pos], softened_gain(complex(1.0, 0.0), los_clear, 1.0), config, 1))

    for surface in unified_surfaces(rx_pos):
        mirrored_tx = reflect_point_across_plane(tx, surface["point"], surface["normal"])
        reflection = line_plane_intersection(mirrored_tx, rx_pos, surface["point"], surface["normal"])
        if reflection is None:
            continue
        clear = True if mitsuba_scene is None else polyline_clear(mitsuba_scene, mi, [tx, reflection, rx_pos])
        candidates.append(
            build_candidate_from_points(
                surface["name"],
                [tx, reflection, rx_pos],
                softened_gain(surface["gain"], clear, 6.0),
                config,
                0,
            )
        )

    for idx, scatter_point in enumerate(unified_scatter_points(rx_pos)):
        clear = True if mitsuba_scene is None else polyline_clear(mitsuba_scene, mi, [tx, scatter_point, rx_pos])
        candidates.append(
            build_candidate_from_points(
                f"scatter_{idx}",
                [tx, scatter_point, rx_pos],
                softened_gain(complex(0.12, 0.0), clear, 10.0 + idx),
                config,
                0,
            )
        )

    train_roof_point = (rx_pos[0], rx_pos[1], rx_pos[2] + 0.8)
    clear = True if mitsuba_scene is None else polyline_clear(mitsuba_scene, mi, [tx, train_roof_point, rx_pos])
    candidates.append(
        build_candidate_from_points(
            "train_roof_scatter",
            [tx, train_roof_point, rx_pos],
            softened_gain(complex(0.08, 0.0), clear, 12.0),
            config,
            0,
        )
    )
    by_name = {candidate.name: candidate for candidate in candidates}
    return sorted(by_name.values(), key=lambda item: abs(item.coefficient), reverse=True)


def fallback_paths_for_sample(config: Dict, station: Dict, rx_pos: Tuple[float, float, float], mitsuba_scene=None, mi=None) -> List[CandidatePath]:
    if is_unified_scenario(config):
        return unified_paths_for_sample(config, station, rx_pos, mitsuba_scene=mitsuba_scene, mi=mi)
    return legacy_paths_for_sample(config, station, rx_pos, mitsuba_scene=mitsuba_scene, mi=mi)


def _append_rows(writer: TraceCsvWriter, time_s: float, extracted: List[CandidatePath]) -> Dict[str, float]:
    timestamp_ns = int(round(time_s * 1e9))
    rows = []
    for path_id, path in enumerate(extracted):
        rows.append(
            {
                "timestamp_ns": timestamp_ns,
                "path_id": path_id,
                "delay_s": path.delay_s,
                "amplitude_real": path.coefficient.real,
                "amplitude_imag": path.coefficient.imag,
                "phase_rad": cmath.phase(path.coefficient),
                "aoa_theta_rad": path.aoa_theta_rad,
                "aoa_phi_rad": path.aoa_phi_rad,
                "aod_theta_rad": path.aod_theta_rad,
                "aod_phi_rad": path.aod_phi_rad,
                "doppler_hz": path.doppler_hz,
                "los_flag": path.los_flag,
            }
        )
    writer.write_rows(rows)
    return {
        "time_s": time_s,
        "path_count": len(rows),
        "max_abs_doppler_hz": max((abs(row["doppler_hz"]) for row in rows), default=0.0),
    }


def station_output_paths(config: Dict, output_paths: Dict, station: Dict, index: int) -> Dict[str, Path]:
    station_name = station_output_name(station, index)
    per_station = dict(output_paths)
    trace_pattern = config["paths"].get("trace_csv_pattern")
    doppler_pattern = config["paths"].get("doppler_plot_pattern")
    path_count_pattern = config["paths"].get("path_count_plot_pattern")
    if trace_pattern:
        per_station["trace_csv"] = resolve_config_relative_path(config, trace_pattern.format(station=station_name))
    if doppler_pattern:
        per_station["doppler_plot"] = resolve_config_relative_path(config, doppler_pattern.format(station=station_name))
    if path_count_pattern:
        per_station["path_count_plot"] = resolve_config_relative_path(config, path_count_pattern.format(station=station_name))
    return per_station


def snapshot_file_prefix(station: Dict, index: int) -> str:
    return station_output_name(station, index)


def export_snapshot_visualizations(
    config: Dict,
    output_paths: Dict,
    station: Dict,
    index: int,
    snapshot_data: Dict,
    mitsuba_scene=None,
    mi=None,
) -> None:
    if not snapshot_data or bool(config.get("ray_tracing", {}).get("skip_snapshot_visualizations", False)):
        return
    prefix = snapshot_file_prefix(station, index)
    tx_pos = station_ray_origin(station)
    output_dir = output_paths["mitsuba_xml"].parent
    for key, data in snapshot_data.items():
        time_s = float(data["time_s"])
        visual_paths = data["paths"]
        export_rays_3d_visualization(
            tx_position=tx_pos,
            rx_position=data["rx_pos"],
            paths=visual_paths,
            output_path=output_dir / f"{prefix}_rays_3d_{key}_t{time_s:.3f}s.png",
            title=f"{prefix} 3D Ray Paths (t = {time_s:.3f}s)",
        )
        export_sample_style_scene(
            tx_position=tx_pos,
            rx_position=data["rx_pos"],
            paths=visual_paths,
            output_path=output_dir / f"{prefix}_coverage_{key}_t{time_s:.3f}s.png",
            scene_cfg={**config["scene"], "frequency_hz_override": float(config["simulation"]["frequency_hz"])},
            barrier_cfg=config["noise_barriers"],
            train_cfg=config["train"],
            title=f"{prefix} Coverage and Ray Paths (t = {time_s:.3f}s)",
        )


def build_planar_array(config: Dict, imports: Dict, key: str):
    defaults = {
        "num_rows": 1,
        "num_cols": 1,
        "vertical_spacing": 0.5,
        "horizontal_spacing": 0.5,
        "pattern": "iso",
        "polarization": "V",
        "polarization_model": "tr38901_2",
    }
    array_cfg = dict(defaults)
    array_cfg.update(config.get("antenna", {}).get(key, {}))
    return imports["PlanarArray"](
        num_rows=int(array_cfg["num_rows"]),
        num_cols=int(array_cfg["num_cols"]),
        vertical_spacing=float(array_cfg["vertical_spacing"]),
        horizontal_spacing=float(array_cfg["horizontal_spacing"]),
        pattern=str(array_cfg["pattern"]),
        polarization=str(array_cfg["polarization"]),
        polarization_model=str(array_cfg.get("polarization_model", "tr38901_2")),
    )


def run_sionna_backend(config: Dict, output_paths: Dict, station: Dict, index: int, samples: List[Tuple[float, Tuple[float, float, float]]]) -> List[Dict[str, float]]:
    imports = try_import_sionna()
    if imports is None:
        raise RuntimeError("Sionna RT is not available.")
    mitsuba_scene_path = prepare_ascii_safe_scene(output_paths)
    scene = imports["load_scene"](str(mitsuba_scene_path), merge_shapes=False)
    scene.frequency = float(config["simulation"]["frequency_hz"])
    scene.tx_array = build_planar_array(config, imports, "tx_array")
    scene.rx_array = build_planar_array(config, imports, "rx_array")
    mi = imports["mi"]
    tx = imports["Transmitter"](name="tx", position=mi.Point3f(*station_ray_origin(station)), orientation=mi.Point3f(0.0, 0.0, 0.0))
    rx = imports["Receiver"](name="rx", position=mi.Point3f(*samples[0][1]), orientation=mi.Point3f(0.0, 0.0, 0.0))
    scene.add(tx)
    scene.add(rx)
    solver = imports["PathSolver"]()
    summary: List[Dict[str, float]] = []
    snapshot_data: Dict[str, Dict] = {}
    mid_step = len(samples) // 2
    progress_interval = max(1, int(config.get("ray_tracing", {}).get("progress_interval_samples", 10)))
    fallback_on_empty = bool(config.get("ray_tracing", {}).get("fallback_on_empty_sionna_paths", True))
    with TraceCsvWriter(output_paths["trace_csv"]) as writer:
        for step_idx, (time_s, rx_pos) in enumerate(samples):
            rx.position = mi.Point3f(*rx_pos)
            tx.look_at(rx)
            rx.look_at(tx)
            paths = solver(
                scene=scene,
                max_depth=int(config["ray_tracing"]["max_depth"]),
                max_num_paths_per_src=int(config["ray_tracing"]["max_num_paths"]),
                samples_per_src=int(config["ray_tracing"]["samples_per_src"]),
                synthetic_array=bool(config["ray_tracing"].get("synthetic_array", True)),
                los=True,
                specular_reflection=True,
                diffuse_reflection=bool(config["ray_tracing"].get("enable_diffuse_reflection", False)),
                refraction=bool(config["ray_tracing"].get("enable_refraction", False)),
                diffraction=bool(config["ray_tracing"].get("enable_diffraction", False)),
                edge_diffraction=bool(config["ray_tracing"].get("enable_edge_diffraction", False)),
                diffraction_lit_region=bool(config["ray_tracing"].get("enable_diffraction_lit_region", True)),
                seed=42,
            )
            extracted = extract_sionna_paths(paths, config)
            if not extracted and fallback_on_empty:
                extracted = fallback_paths_for_sample(config, station, rx_pos)
            summary.append(_append_rows(writer, time_s, extracted))
            if step_idx == 0 or (step_idx + 1) % progress_interval == 0 or step_idx == len(samples) - 1:
                print(
                    f"[{station_label(station, index)}] sample {step_idx + 1}/{len(samples)} "
                    f"paths={len(extracted)} time_s={time_s:.3f}",
                    flush=True,
                )
            if step_idx == 0:
                snapshot_data["start"] = {"time_s": time_s, "rx_pos": rx_pos, "paths": extracted}
            if step_idx == mid_step:
                snapshot_data["mid"] = {"time_s": time_s, "rx_pos": rx_pos, "paths": extracted}
            snapshot_data["end"] = {"time_s": time_s, "rx_pos": rx_pos, "paths": extracted}
    export_snapshot_visualizations(config, output_paths, station, index, snapshot_data)
    return summary


def run_fallback_backend(config: Dict, output_paths: Dict, station: Dict, index: int, samples: List[Tuple[float, Tuple[float, float, float]]]) -> List[Dict[str, float]]:
    mi = try_import_mitsuba()
    mitsuba_scene = None
    if mi is not None and output_paths["mitsuba_xml"].exists():
        try:
            mitsuba_scene_path = prepare_ascii_safe_scene(output_paths)
            mitsuba_scene = mi.load_file(str(mitsuba_scene_path))
            print(f"Loaded Mitsuba scene from {safe_path_text(mitsuba_scene_path)}")
        except Exception as exc:
            print(f"Warning: Could not load Mitsuba scene: {safe_exception_text(exc)}")
    summary: List[Dict[str, float]] = []
    snapshot_data: Dict[str, Dict] = {}
    mid_step = len(samples) // 2
    with TraceCsvWriter(output_paths["trace_csv"]) as writer:
        for step_idx, (time_s, rx_pos) in enumerate(samples):
            extracted = fallback_paths_for_sample(config, station, rx_pos, mitsuba_scene=mitsuba_scene, mi=mi)
            summary.append(_append_rows(writer, time_s, extracted))
            if step_idx == 0:
                snapshot_data["start"] = {"time_s": time_s, "rx_pos": rx_pos, "paths": extracted}
            if step_idx == mid_step:
                snapshot_data["mid"] = {"time_s": time_s, "rx_pos": rx_pos, "paths": extracted}
            snapshot_data["end"] = {"time_s": time_s, "rx_pos": rx_pos, "paths": extracted}
    export_snapshot_visualizations(config, output_paths, station, index, snapshot_data, mitsuba_scene=mitsuba_scene, mi=mi)
    return summary


def run_station(config: Dict, base_output_paths: Dict, station: Dict, index: int, force_fallback: bool, samples: List[Tuple[float, Tuple[float, float, float]]]) -> Tuple[str, List[Dict[str, float]], Dict[str, Path]]:
    output_paths = station_output_paths(config, base_output_paths, station, index)
    backend = "sionna"
    try:
        if force_fallback:
            raise RuntimeError("Fallback explicitly requested.")
        summary = run_sionna_backend(config, output_paths, station, index, samples)
    except Exception as exc:
        if bool(config.get("ray_tracing", {}).get("require_sionna_backend", False)):
            raise
        backend = "fallback"
        print(f"Sionna RT backend unavailable or failed for {station_label(station, index)}: {safe_exception_text(exc)}")
        summary = run_fallback_backend(config, output_paths, station, index, samples)
    if not bool(config.get("ray_tracing", {}).get("skip_station_validation_plots", False)):
        export_validation_plots(summary, output_paths["doppler_plot"], output_paths["path_count_plot"])
    print(f"[{station_label(station, index)}] backend={backend} trace={safe_path_text(output_paths['trace_csv'])}")
    return backend, summary, output_paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Sionna RT with Mitsuba-assisted fallback.")
    parser.add_argument(
        "--config",
        default=str(ROOT / "phase1_pipeline" / "config" / "config.yaml"),
        help="Path to the pipeline YAML configuration file.",
    )
    parser.add_argument("--force-fallback", action="store_true", help="Skip Sionna RT and use fallback.")
    args = parser.parse_args()

    config = load_config(args.config)
    output_paths = resolve_output_paths(config)
    samples = fallback_trajectory_samples(config)
    if is_external_loop_scenario(config):
        stations = external_loop_base_stations(config)
    else:
        stations = all_base_stations(config) if is_unified_scenario(config) else [active_base_station(config)]

    summaries_by_station: Dict[str, List[Dict[str, float]]] = {}
    trace_manifest = []
    for index, station in enumerate(stations):
        backend, summary, station_paths = run_station(config, output_paths, station, index, args.force_fallback, samples)
        label = station_label(station, index)
        summaries_by_station[label] = summary
        trace_manifest.append(
            {
                "station": label,
                "output_name": station_output_name(station, index),
                "backend": backend,
                "trace_csv": str(station_paths["trace_csv"]),
                "doppler_plot": str(station_paths["doppler_plot"]),
                "path_count_plot": str(station_paths["path_count_plot"]),
            }
        )

    if is_unified_scenario(config) or is_external_loop_scenario(config):
        if not bool(config.get("ray_tracing", {}).get("skip_station_validation_plots", False)):
            export_multi_station_validation_plots(summaries_by_station, output_paths["doppler_plot"], output_paths["path_count_plot"])
        manifest_path = resolve_config_relative_path(config, config["paths"].get("trace_manifest", "output_unified/trace_manifest.json"))
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with manifest_path.open("w", encoding="utf-8") as handle:
            json.dump(trace_manifest, handle, indent=2)
        print(f"Unified trace manifest: {safe_path_text(manifest_path)}")

    print(f"\n{'=' * 60}")
    print("Ray-tracing completed")
    print(f"{'=' * 60}")
    print(f"Scene XML: {safe_path_text(output_paths['mitsuba_xml'])}")
    print(f"Scene metadata: {safe_path_text(output_paths['scene_metadata'])}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
