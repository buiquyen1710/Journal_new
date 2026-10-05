from __future__ import annotations

import json
from pathlib import Path

import polyscope as ps
from sionna_rt_gui.config import load_config
from sionna_rt_gui.reload import AppHolder


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "phase1_pipeline" / "output_vietnam_rt_corrected"
CONFIG = OUT / "sionna_rt_gui_vietnam.yaml"
META = OUT / "scene_metadata.json"


def main() -> None:
    metadata = json.loads(META.read_text(encoding="utf-8"))
    gnb_c = metadata["all_gnb_positions_m"][2]
    # Snapshot near tunnel portal; visible and normally produces paths with current scene.
    rx = metadata["rx_trajectory_samples"][58]

    cfg = load_config(str(CONFIG))
    cfg.paths.auto_update = False
    cfg.radio_map.auto_update = False
    holder = AppHolder(cfg, scene_filename=None)
    app = holder.app

    app.add_radio_device(gnb_c, is_transmitter=True, allow_auto_update=False)
    app.add_radio_device(rx, is_transmitter=False, allow_auto_update=False)
    try:
        app.scene.get("tx-0").look_at(app.scene.get("rx-0"))
        app.scene.get("rx-0").look_at(app.scene.get("tx-0"))
    except Exception:
        pass

    app.cfg.paths.samples_per_src = 20000
    app.cfg.paths.max_depth = 5
    app.cfg.paths.los = True
    app.cfg.paths.specular_reflection = True
    app.cfg.paths.diffuse_reflection = True
    app.cfg.paths.refraction = False
    app.cfg.paths.diffraction = False
    app.update_paths(show=True)
    ps.look_at((gnb_c[0], gnb_c[1] - 260.0, gnb_c[2] + 180.0), (rx[0], rx[1], rx[2]))
    holder.show()


if __name__ == "__main__":
    main()
