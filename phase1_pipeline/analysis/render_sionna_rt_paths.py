
from __future__ import annotations

import argparse
import json
import math
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phase1_pipeline.common import load_config, resolve_output_paths, subtract, vector_length
from phase1_pipeline.raytracing.run_sionna_rt import (
    build_planar_array,
    fallback_trajectory_samples,
    prepare_ascii_safe_scene,
    station_ray_origin,
    try_import_sionna,
)
from phase1_pipeline.scenarios import all_base_stations, station_label, station_output_name, unified_module_for_x

OUTPUT_DIR = ROOT / 'phase1_pipeline' / 'sionna_rt_ray_renders'
SNAPSHOT_X = {
    'TX1': 500.0,
    'TX2': 980.0,
    'TX3': 1550.0,
    'TX4': 2320.0,
    'TX5': 1220.0,
}




def _box_faces(center, size):
    cx, cy, cz = center
    sx, sy, sz = size
    hx, hy, hz = sx / 2.0, sy / 2.0, sz / 2.0
    v = [
        (cx-hx, cy-hy, cz-hz), (cx+hx, cy-hy, cz-hz), (cx+hx, cy+hy, cz-hz), (cx-hx, cy+hy, cz-hz),
        (cx-hx, cy-hy, cz+hz), (cx+hx, cy-hy, cz+hz), (cx+hx, cy+hy, cz+hz), (cx-hx, cy+hy, cz+hz),
    ]
    return [[v[i] for i in ids] for ids in [(0,1,2,3),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]]


def _add_box(ax, center, size, color, alpha=0.22):
    ax.add_collection3d(Poly3DCollection(_box_faces(center, size), facecolors=color, edgecolors='#333333', linewidths=0.3, alpha=alpha))


def _draw_simple_context(ax, tx_pos, rx_pos, module_kind):
    x0 = (tx_pos[0] + rx_pos[0]) * 0.5
    span = max(140.0, abs(tx_pos[0] - rx_pos[0]) + 80.0)
    if module_kind == 'tunnel':
        _add_box(ax, (x0, 0.0, 0.0), (span, 11.0, 0.25), '#777777', 0.18)
        _add_box(ax, (x0, -5.25, 3.75), (span, 0.35, 7.5), '#7f8790', 0.16)
        _add_box(ax, (x0, 5.25, 3.75), (span, 0.35, 7.5), '#7f8790', 0.16)
        _add_box(ax, (x0, 0.0, 7.5), (span, 11.0, 0.30), '#7f8790', 0.10)
    elif module_kind == 'viaduct':
        _add_box(ax, (x0, 0.0, 12.0), (span, 8.0, 0.35), '#8c969f', 0.20)
        _add_box(ax, (x0, -3.8, 14.0), (span, 0.30, 2.8), '#bdb8a8', 0.25)
        _add_box(ax, (x0, 3.8, 14.0), (span, 0.30, 2.8), '#bdb8a8', 0.25)
    else:
        _add_box(ax, (x0, 0.0, 0.0), (span, 12.0, 0.25), '#807b70', 0.18)
        _add_box(ax, (x0, -3.8, 1.5), (span, 0.30, 3.0), '#bdb8a8', 0.20)
        _add_box(ax, (x0, 3.8, 1.5), (span, 0.30, 3.0), '#bdb8a8', 0.20)
    # train body near RX
    _add_box(ax, (rx_pos[0], rx_pos[1], rx_pos[2]-1.9), (25.0, 3.2, 3.7), '#dceaf3', 0.38)


def _set_equal_axes(ax, points):
    pts = np.asarray(points, dtype=float)
    mins = np.nanmin(pts, axis=0)
    maxs = np.nanmax(pts, axis=0)
    center = (mins + maxs) * 0.5
    radius = max(float(np.max(maxs - mins)) * 0.55, 10.0)
    ax.set_xlim(center[0] - radius, center[0] + radius)
    ax.set_ylim(center[1] - radius, center[1] + radius)
    ax.set_zlim(max(0.0, center[2] - radius * 0.35), center[2] + radius * 0.65)


def render_segments_3d(paths, tx_pos, rx_pos, module_kind, output_file, title):
    from sionna.rt.utils import paths_to_segments
    starts, ends, colors = paths_to_segments(paths)
    starts = np.asarray(starts, dtype=float)
    ends = np.asarray(ends, dtype=float)
    colors = np.asarray(colors, dtype=float)
    fig = plt.figure(figsize=(13, 8.5))
    ax = fig.add_subplot(111, projection='3d')
    _draw_simple_context(ax, tx_pos, rx_pos, module_kind)
    all_pts = [tx_pos, rx_pos]
    for i, (s0, e0) in enumerate(zip(starts, ends)):
        all_pts.extend([s0, e0])
        c = colors[i] if i < len(colors) else np.array([1.0, 0.2, 0.1])
        # Clip possible alpha channel and boost visibility.
        color = tuple(np.clip(c[:3], 0, 1))
        ax.plot([s0[0], e0[0]], [s0[1], e0[1]], [s0[2], e0[2]], color=color, linewidth=2.4, alpha=0.96)
    ax.scatter(*tx_pos, color='red', marker='*', s=190, label='TX/gNB')
    ax.scatter(*rx_pos, color='blue', marker='o', s=90, label='RX/train')
    _set_equal_axes(ax, all_pts)
    ax.set_xlabel('X (m)')
    ax.set_ylabel('Y (m)')
    ax.set_zlabel('Z (m)')
    ax.view_init(elev=22, azim=-58)
    ax.grid(True, alpha=0.25)
    ax.legend(loc='upper left')
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(output_file, dpi=190, bbox_inches='tight', facecolor='white')
    plt.close(fig)

def closest_sample(samples, target_x):
    return min(samples, key=lambda item: abs(item[1][0] - target_x))


def count_valid_paths(paths) -> int:
    try:
        valid = paths.valid.numpy()
        return int(valid.sum())
    except Exception:
        return -1




def csv_resolved_path_count(config: Dict, output_name: str, time_s: float) -> int | None:
    csv_path = ROOT / 'phase1_pipeline' / 'output_unified' / f'{output_name}.csv'
    if not csv_path.exists():
        return None
    timestamp_ns = int(round(time_s * 1e9))
    try:
        df = pd.read_csv(csv_path, usecols=['timestamp_ns'])
        counts = df.groupby('timestamp_ns').size()
        if timestamp_ns in counts.index:
            return int(counts.loc[timestamp_ns])
        nearest = int(np.asarray(counts.index)[np.argmin(np.abs(np.asarray(counts.index) - timestamp_ns))])
        return int(counts.loc[nearest])
    except Exception:
        return None


def camera_for_snapshot(mi, tx_pos, rx_pos, station_id: str, view: str):
    mid = tuple((tx_pos[i] + rx_pos[i]) * 0.5 for i in range(3))
    dx = max(80.0, abs(rx_pos[0] - tx_pos[0]) * 0.35)
    if view == 'close':
        position = (rx_pos[0] - 45.0, rx_pos[1] - 65.0, rx_pos[2] + 35.0)
        look_at = (rx_pos[0], rx_pos[1], rx_pos[2] + 1.0)
    elif station_id == 'TX3':
        # Side/top camera for tunnel so paths inside the tunnel remain visible.
        position = (rx_pos[0] - 38.0, rx_pos[1] - 34.0, rx_pos[2] + 23.0)
        look_at = (rx_pos[0], rx_pos[1], rx_pos[2] + 0.5)
    else:
        position = (mid[0] - dx, mid[1] - 85.0, max(tx_pos[2], rx_pos[2]) + 45.0)
        look_at = (mid[0], mid[1], (tx_pos[2] + rx_pos[2]) * 0.5)
    return __import__('sionna.rt', fromlist=['Camera']).Camera(
        position=mi.Point3f(*position),
        look_at=mi.Point3f(*look_at),
    )


def render_one(config: Dict, station: Dict, station_index: int, samples, args) -> List[Dict]:
    imports = try_import_sionna()
    if imports is None:
        raise RuntimeError('Sionna RT is not available in this Python environment.')
    mi = imports['mi']
    load_scene = imports['load_scene']
    Transmitter = imports['Transmitter']
    Receiver = imports['Receiver']
    PathSolver = imports['PathSolver']

    station_id = str(station.get('name', f'TX{station_index+1}')).split('_')[0].upper()
    output_name = station_output_name(station, station_index)
    target_x = float(args.snapshot_x) if args.snapshot_x is not None else SNAPSHOT_X.get(station_id, float(station['position_m'][0]))
    time_s, rx_pos = closest_sample(samples, target_x)
    tx_pos = station_ray_origin(station)

    output_paths = resolve_output_paths(config)
    scene_path = prepare_ascii_safe_scene(output_paths)
    scene = load_scene(str(scene_path), merge_shapes=False)
    scene.frequency = float(config['simulation']['frequency_hz'])
    scene.tx_array = build_planar_array(config, imports, 'tx_array')
    scene.rx_array = build_planar_array(config, imports, 'rx_array')

    tx = Transmitter(name='tx', position=mi.Point3f(*tx_pos), orientation=mi.Point3f(0.0, 0.0, 0.0))
    rx = Receiver(name='rx', position=mi.Point3f(*rx_pos), orientation=mi.Point3f(0.0, 0.0, 0.0))
    scene.add(tx)
    scene.add(rx)
    tx.look_at(rx)
    rx.look_at(tx)

    solver = PathSolver()
    paths = solver(
        scene=scene,
        max_depth=int(args.max_depth if args.max_depth is not None else config['ray_tracing']['max_depth']),
        max_num_paths_per_src=int(args.max_num_paths if args.max_num_paths is not None else config['ray_tracing']['max_num_paths']),
        samples_per_src=int(args.samples_per_src if args.samples_per_src is not None else config['ray_tracing']['samples_per_src']),
        synthetic_array=bool(config['ray_tracing'].get('synthetic_array', True)),
        los=True,
        specular_reflection=True,
        diffuse_reflection=bool(config['ray_tracing'].get('enable_diffuse_reflection', False)),
        refraction=bool(config['ray_tracing'].get('enable_refraction', False)),
        diffraction=bool(config['ray_tracing'].get('enable_diffraction', False)),
        edge_diffraction=bool(config['ray_tracing'].get('enable_edge_diffraction', False)),
        diffraction_lit_region=bool(config['ray_tracing'].get('enable_diffraction_lit_region', True)),
        seed=int(args.seed),
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    module = unified_module_for_x(rx_pos[0])
    resolved_csv_count = csv_resolved_path_count(config, output_name, time_s)
    rendered = []
    views = ['overview'] if args.view == 'overview' else ['close'] if args.view == 'close' else ['overview', 'close']
    for view in views:
        camera = camera_for_snapshot(mi, tx_pos, rx_pos, station_id, view)
        filename = OUTPUT_DIR / f'{output_name}_sionna_rt_paths_{view}_x{rx_pos[0]:.0f}m.png'
        scene.render_to_file(
            camera=camera,
            filename=str(filename),
            paths=paths,
            resolution=(int(args.width), int(args.height)),
            num_samples=int(args.render_samples),
            fov=float(args.fov),
            show_devices=bool(args.show_devices),
            show_orientations=False,
            lighting_scale=float(args.lighting_scale),
        )
        segment_file = OUTPUT_DIR / f'{output_name}_sionna_rt_segments_3d_{view}_x{rx_pos[0]:.0f}m.png'
        render_segments_3d(paths, tx_pos, rx_pos, module['kind'], segment_file, f'{station_id} {station_label(station, station_index)} - Sionna RT path segments ({view})')
        rendered.append({
            'station': station_id,
            'label': station_label(station, station_index),
            'view': view,
            'file': str(filename),
            'segments_3d_file': str(segment_file),
            'rx_position_m': [float(x) for x in rx_pos],
            'tx_position_m': [float(x) for x in tx_pos],
            'time_s': float(time_s),
            'module': module['kind'],
            'sionna_valid_paths_before_csv_filter': count_valid_paths(paths),
            'resolved_paths_after_csv_filter': resolved_csv_count,
            'path_count_note': 'Sionna valid paths are raw valid paths in the Paths object before dynamic-range filtering and max_paths_after_filter. Resolved paths match the CSV/path-count plot after filtering.',
        })
        print(filename)
    return rendered


def main():
    parser = argparse.ArgumentParser(description='Render Sionna RT propagation paths directly with Scene.render_to_file(paths=...).')
    parser.add_argument('--config', default=str(ROOT / 'phase1_pipeline' / 'config' / 'config.yaml'))
    parser.add_argument('--station', default='all', help='all, TX1, TX2, TX3, TX4, TX5, or station index 0-4')
    parser.add_argument('--snapshot-x', type=float, default=None)
    parser.add_argument('--view', choices=['overview', 'close', 'both'], default='both')
    parser.add_argument('--samples-per-src', type=int, default=3000)
    parser.add_argument('--max-depth', type=int, default=None)
    parser.add_argument('--max-num-paths', type=int, default=None)
    parser.add_argument('--render-samples', type=int, default=64)
    parser.add_argument('--width', type=int, default=1200)
    parser.add_argument('--height', type=int, default=820)
    parser.add_argument('--fov', type=float, default=48.0)
    parser.add_argument('--lighting-scale', type=float, default=1.0)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--show-devices', action='store_true', help='Show Sionna TX/RX device markers. Off by default because markers can hide paths.')
    args = parser.parse_args()

    config = load_config(args.config)
    samples = fallback_trajectory_samples(config)
    stations = list(all_base_stations(config))
    selected = []
    req = str(args.station).upper()
    for idx, station in enumerate(stations):
        sid = str(station.get('name', f'TX{idx+1}')).split('_')[0].upper()
        if req == 'ALL' or req == sid or req == str(idx):
            selected.append((idx, station))
    if not selected:
        raise SystemExit(f'No station matched: {args.station}')

    manifest = []
    for idx, station in selected:
        manifest.extend(render_one(config, station, idx, samples, args))
    manifest_path = OUTPUT_DIR / 'sionna_rt_ray_render_manifest.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Manifest: {manifest_path}')


if __name__ == '__main__':
    main()
