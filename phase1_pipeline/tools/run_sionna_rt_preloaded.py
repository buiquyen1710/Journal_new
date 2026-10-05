from __future__ import annotations

import argparse
import ctypes  # noqa: F401
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="Preload Windows DLL-sensitive modules before running Sionna RT.")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    from sionna.rt import PathSolver, PlanarArray, Receiver, Transmitter, load_scene  # noqa: F401
    from phase1_pipeline.raytracing import run_sionna_rt

    sys.argv = ["run_sionna_rt.py", "--config", args.config]
    run_sionna_rt.main()


if __name__ == "__main__":
    main()
