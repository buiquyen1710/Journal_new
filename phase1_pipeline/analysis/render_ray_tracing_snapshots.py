
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from phase1_pipeline.common import load_config
from phase1_pipeline.raytracing.run_sionna_rt import (
    fallback_paths_for_sample,
    fallback_trajectory_samples,
    station_ray_origin,
)
from phase1_pipeline.scenarios import all_base_stations, station_label, station_output_name, unified_module_for_x

OUTPUT_DIR = ROOT / 'phase1_pipeline' / 'ray_visualizations_3d'

SNAPSHOT_X = {
    'TX1': 350.0,
    'TX2': 850.0,
    'TX3': 1450.0,
    'TX4': 2450.0,
    'TX5': 1150.0,
}


def box_faces(center, size):
    cx, cy, cz = center
    sx, sy, sz = size
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    v = [
        (cx-hx, cy-hy, cz-hz), (cx+hx, cy-hy, cz-hz), (cx+hx, cy+hy, cz-hz), (cx-hx, cy+hy, cz-hz),
        (cx-hx, cy-hy, cz+hz), (cx+hx, cy-hy, cz+hz), (cx+hx, cy+hy, cz+hz), (cx-hx, cy+hy, cz+hz),
    ]
    return [[v[i] for i in ids] for ids in [(0,1,2,3),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]]


def add_box(ax, center, size, color, alpha=0.35, edge='#222222', linewidth=0.4):
    ax.add_collection3d(Poly3DCollection(box_faces(center, size), facecolors=color, edgecolors=edge, linewidths=linewidth, alpha=alpha))


def equal_axes(ax, xs, ys, zs):
    xmid, ymid, zmid = (max(xs)+min(xs))/2, (max(ys)+min(ys))/2, (max(zs)+min(zs))/2
    radius = max(max(xs)-min(xs), max(ys)-min(ys), max(zs)-min(zs), 1.0) / 2
    ax.set_xlim(xmid-radius, xmid+radius)
    ax.set_ylim(ymid-radius, ymid+radius)
    ax.set_zlim(max(0, zmid-radius*0.5), zmid+radius*0.65)


def closest_sample(samples, target_x):
    return min(samples, key=lambda item: abs(item[1][0] - target_x))


def draw_scene_geometry(ax, rx_pos, tx_pos, module_kind, config):
    x = rx_pos[0]
    # Local ground/deck slab
    if module_kind == 'viaduct':
        add_box(ax, (x, 0, 12.0), (210, 8.5, 0.45), '#7d8792', alpha=0.28)
        add_box(ax, (x, -3.8, 14.2), (210, 0.35, 2.8), '#b9b9ad', alpha=0.42)
        add_box(ax, (x, 3.8, 14.2), (210, 0.35, 2.8), '#b9b9ad', alpha=0.42)
        for dx in (-75, 0, 75):
            add_box(ax, (x+dx, 0, 6.0), (1.6, 1.6, 12.0), '#88939c', alpha=0.22)
    elif module_kind == 'tunnel':
        add_box(ax, (x, 0, 0.0), (220, 11.0, 0.35), '#7a7770', alpha=0.28)
        add_box(ax, (x, -5.25, 3.75), (220, 0.45, 7.5), '#747b83', alpha=0.32)
        add_box(ax, (x, 5.25, 3.75), (220, 0.45, 7.5), '#747b83', alpha=0.32)
        add_box(ax, (x, 0, 7.55), (220, 11.0, 0.45), '#6d747b', alpha=0.25)
    elif module_kind in {'transition_in', 'transition_out'}:
        add_box(ax, (x, 0, 0.0), (220, 12.0, 0.35), '#7a7770', alpha=0.24)
        add_box(ax, (x, -5.5, 3.0), (220, 1.0, 6.0), '#8b7e62', alpha=0.25)
        add_box(ax, (x, 5.5, 3.0), (220, 1.0, 6.0), '#8b7e62', alpha=0.25)
        add_box(ax, (1300.0 if module_kind == 'transition_in' else 1600.0, 0, 3.8), (4.0, 11.0, 7.6), '#525a63', alpha=0.18)
    else:
        add_box(ax, (x, 0, 0.0), (220, 12.0, 0.35), '#7a7770', alpha=0.24)
        add_box(ax, (x, -3.8, 1.4), (220, 0.35, 2.8), '#b9b9ad', alpha=0.32)
        add_box(ax, (x, 3.8, 1.4), (220, 0.35, 2.8), '#b9b9ad', alpha=0.32)

    # Rails and train body
    for rail_y in (-0.72, 0.72):
        ax.plot([x-105, x+105], [rail_y, rail_y], [rx_pos[2]-4.0, rx_pos[2]-4.0], color='#2b2f33', linewidth=2.0, alpha=0.85)
    train_len = float(config['train'].get('length_m', 25.0))
    train_width = float(config['train'].get('width_m', 3.2))
    body_height = float(config['train'].get('body_height_m', 3.7))
    roof_z = rx_pos[2] - 0.35
    add_box(ax, (rx_pos[0], rx_pos[1], roof_z - body_height/2), (train_len, train_width, body_height), '#dceaf3', alpha=0.58, edge='#385566', linewidth=0.8)


def render_snapshot(config, station, station_index, samples):
    name = str(station.get('name', f'TX{station_index+1}'))
    station_id = name.split('_')[0].upper() if name else f'TX{station_index+1}'
    output_name = station_output_name(station, station_index)
    target_x = SNAPSHOT_X.get(station_id, station.get('position_m', [0])[0])
    time_s, rx_pos = closest_sample(samples, target_x)
    tx_pos = station_ray_origin(station)
    module = unified_module_for_x(rx_pos[0])
    paths = fallback_paths_for_sample(config, station, rx_pos)[:12]

    fig = plt.figure(figsize=(14, 9))
    ax = fig.add_subplot(111, projection='3d')
    draw_scene_geometry(ax, rx_pos, tx_pos, module['kind'], config)

    max_amp = max(abs(getattr(p, 'coefficient', 1.0)) for p in paths) if paths else 1.0
    xs, ys, zs = [tx_pos[0], rx_pos[0]], [tx_pos[1], rx_pos[1]], [tx_pos[2], rx_pos[2]]
    los_count = 0
    nlos_count = 0
    for idx, path in enumerate(paths):
        pts = list(path.points) if getattr(path, 'points', None) else [tx_pos, rx_pos]
        xs.extend([p[0] for p in pts])
        ys.extend([p[1] for p in pts])
        zs.extend([p[2] for p in pts])
        is_los = int(getattr(path, 'los_flag', 0)) == 1
        los_count += int(is_los)
        nlos_count += int(not is_los)
        amp = abs(getattr(path, 'coefficient', 1.0))
        lw = 1.2 + 3.0 * (amp / max_amp if max_amp else 0.0)
        color = '#ff2d2d' if is_los else '#00b7ff'
        style = '-' if is_los else '--'
        ax.plot([p[0] for p in pts], [p[1] for p in pts], [p[2] for p in pts], color=color, linestyle=style, linewidth=lw, alpha=0.92)
        for p in pts[1:-1]:
            ax.scatter(p[0], p[1], p[2], color='#ffd166', s=42, marker='o', edgecolor='#5a3b00', linewidth=0.5)

    ax.scatter(*tx_pos, color='#ff0000', s=180, marker='*', label='TX / gNB')
    ax.scatter(*rx_pos, color='#0a5cff', s=110, marker='o', label='RX on train')
    ax.text(tx_pos[0], tx_pos[1], tx_pos[2]+3, station_id, color='#8b0000', fontsize=10, weight='bold')
    ax.text(rx_pos[0], rx_pos[1], rx_pos[2]+2, 'RX', color='#003b9a', fontsize=10, weight='bold')

    equal_axes(ax, xs, ys, zs)
    ax.set_xlabel('X along railway (m)')
    ax.set_ylabel('Y lateral (m)')
    ax.set_zlabel('Z height (m)')
    ax.view_init(elev=22, azim=-58)
    ax.grid(True, alpha=0.25)
    ax.legend(loc='upper left')
    ax.set_title(f'{station_id} {station_label(station, station_index)} - 3D ray tracing snapshot\nmodule={module["kind"]}, x_rx={rx_pos[0]:.1f} m, t={time_s:.3f} s, paths={los_count} LOS + {nlos_count} NLOS')
    fig.tight_layout()
    out = OUTPUT_DIR / f'{output_name}_ray_tracing_3d_x{rx_pos[0]:.0f}m.png'
    fig.savefig(out, dpi=190, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return out


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config = load_config(ROOT / 'phase1_pipeline' / 'config' / 'config.yaml')
    samples = fallback_trajectory_samples(config)
    outputs = []
    for idx, station in enumerate(all_base_stations(config)):
        outputs.append(render_snapshot(config, station, idx, samples))
    print('Generated ray visualization images:')
    for path in outputs:
        print(path)


if __name__ == '__main__':
    main()
