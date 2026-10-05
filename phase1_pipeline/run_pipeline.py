from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from shutil import which

from phase1_pipeline.common import load_config, repo_root, resolve_output_paths


def safe_text(value: object) -> str:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return str(value).encode(encoding, errors="backslashreplace").decode(encoding, errors="replace")


def run_command(command, cwd: Path) -> None:
    print("Running:", " ".join(safe_text(part) for part in command))
    subprocess.run(command, cwd=str(cwd), check=True)


def blender_available(blender_executable: str) -> bool:
    if Path(blender_executable).exists():
        return True
    return which(blender_executable) is not None


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the full Blender -> Mitsuba -> ray-tracing pipeline.")
    parser.add_argument(
        "--config",
        default=str(repo_root() / "phase1_pipeline" / "config" / "config.yaml"),
        help="Path to the pipeline YAML configuration file.",
    )
    parser.add_argument(
        "--blender-executable",
        default=os.environ.get("BLENDER_BIN", "blender"),
        help="Blender executable path. Defaults to BLENDER_BIN or `blender`.",
    )
    parser.add_argument("--force-fallback", action="store_true", help="Skip Sionna RT and run the fallback solver.")
    parser.add_argument("--skip-blender", action="store_true", help="Assume the scene and XML already exist.")
    parser.add_argument(
        "--source-blend",
        help="External .blend file to prepare when scenario.type is external_loop_3000m.",
    )
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    repo = repo_root()
    config = load_config(config_path)
    output_paths = resolve_output_paths(config)
    scenario_type = str(config.get("scenario", {}).get("type", ""))
    if not args.skip_blender and blender_available(args.blender_executable):
        if scenario_type == "external_loop_3000m":
            source_blend = args.source_blend or config.get("external_scene", {}).get("source_blend")
            if not source_blend:
                raise ValueError("external_loop_3000m requires --source-blend or external_scene.source_blend.")
            run_command(
                [
                    args.blender_executable,
                    "--background",
                    "--python",
                    str(repo / "phase1_pipeline" / "blender" / "prepare_external_loop_scene.py"),
                    "--",
                    "--config",
                    str(config_path),
                    "--source-blend",
                    str(source_blend),
                ],
                cwd=repo,
            )
            if not output_paths["blend_file"].exists():
                raise FileNotFoundError(f"Prepared blend was not created: {output_paths['blend_file']}")
        else:
            run_command(
                [
                    args.blender_executable,
                    "--background",
                    "--python",
                    str(repo / "phase1_pipeline" / "blender" / "generate_scene.py"),
                    "--",
                    "--config",
                    str(config_path),
                ],
                cwd=repo,
            )
        run_command(
            [
                args.blender_executable,
                str(output_paths["blend_file"]),
                "--background",
                "--python",
                str(repo / "phase1_pipeline" / "export" / "export_mitsuba.py"),
                "--",
                "--config",
                str(config_path),
            ],
            cwd=repo,
        )
    elif not args.skip_blender:
        print("Blender executable not found. Falling back to direct Mitsuba scene export without .blend generation.")
        run_command(
            [sys.executable, "-m", "phase1_pipeline.export.export_mitsuba_fallback", "--config", str(config_path)],
            cwd=repo,
        )

    command = [sys.executable, "-m", "phase1_pipeline.raytracing.run_sionna_rt", "--config", str(config_path)]
    if args.force_fallback:
        command.append("--force-fallback")
    run_command(command, cwd=repo)


if __name__ == "__main__":
    main()
