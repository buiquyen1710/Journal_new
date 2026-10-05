from __future__ import annotations

import json
import math
import os
import ast
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    yaml = None
    YAML_IMPORT_ERROR = exc
else:
    YAML_IMPORT_ERROR = None


SPEED_OF_LIGHT_M_S = 299_792_458.0


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_config(config_path: str | os.PathLike[str]) -> Dict[str, Any]:
    path = Path(config_path).resolve()
    with path.open("r", encoding="utf-8") as handle:
        if yaml is not None:
            data = yaml.safe_load(handle)
        else:
            data = parse_minimal_yaml(handle.read())
    if not isinstance(data, dict):
        raise ValueError(f"Config at {path} did not parse as a mapping.")
    data["_config_path"] = str(path)
    data["_repo_root"] = str(repo_root())
    return data


def parse_minimal_scalar(value: str) -> Any:
    value = value.strip()
    if value == "":
        return {}
    lowered = value.lower()
    if lowered in {"null", "none", "~"}:
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if value.startswith("[") and value.endswith("]"):
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError):
            inner = value[1:-1].strip()
            if not inner:
                return []
            return [parse_minimal_scalar(part.strip()) for part in inner.split(",")]
    try:
        if any(ch in value for ch in (".", "e", "E")):
            return float(value)
        return int(value)
    except ValueError:
        return value.strip("'\"")


def parse_minimal_yaml(text: str) -> Dict[str, Any]:
    root: Dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    pending: list[tuple[int, str, Dict[str, Any]]] = []
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if line.startswith("- "):
            item_text = line[2:].strip()
            if not isinstance(parent, list):
                if not pending:
                    raise ValueError("List item without a pending key in YAML config.")
                _, key, container = pending.pop()
                new_list: list[Any] = []
                container[key] = new_list
                stack.append((indent - 1, new_list))
                parent = new_list
            if ":" in item_text:
                key, value = item_text.split(":", 1)
                item: Dict[str, Any] = {key.strip(): parse_minimal_scalar(value)}
                parent.append(item)
                stack.append((indent, item))
            else:
                parent.append(parse_minimal_scalar(item_text))
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not isinstance(parent, dict):
            raise ValueError(f"Cannot assign key {key!r} under a YAML list.")
        if value == "":
            child: Dict[str, Any] = {}
            parent[key] = child
            pending.append((indent, key, parent))
            stack.append((indent, child))
        else:
            parent[key] = parse_minimal_scalar(value)
    return root


def dump_json(path: str | os.PathLike[str], payload: Dict[str, Any]) -> None:
    target = ensure_parent(Path(path).resolve())
    with target.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def resolve_output_paths(config: Dict[str, Any]) -> Dict[str, Path]:
    cfg_path = Path(config["_config_path"])
    base = cfg_path.parent.parent
    out_cfg = config["paths"]
    resolved = {}
    for key, rel in out_cfg.items():
        resolved[key] = (base / rel).resolve()
    for key in ("blend_file", "mitsuba_xml", "trace_csv", "doppler_plot", "path_count_plot", "scene_metadata"):
        ensure_parent(resolved[key])
    resolved["mesh_dir"].mkdir(parents=True, exist_ok=True)
    return resolved


def resolve_config_relative_path(config: Dict[str, Any], relative_path: str) -> Path:
    cfg_path = Path(config["_config_path"])
    return (cfg_path.parent.parent / relative_path).resolve()


def railway_duration_s(config: Dict[str, Any]) -> float:
    sim = config["simulation"]
    duration = sim.get("duration_s")
    if duration is not None:
        return float(duration)
    scene_length = float(config["scene"]["length_m"])
    speed = float(sim["train_speed_kmh"]) / 3.6
    return scene_length / speed


def wavelength_m(frequency_hz: float) -> float:
    return SPEED_OF_LIGHT_M_S / frequency_hz


def parse_cli(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--config",
        default=str(repo_root() / "phase1_pipeline" / "config" / "config.yaml"),
        help="Path to the YAML configuration file.",
    )
    return parser


def vector_length(vector: Iterable[float]) -> float:
    x, y, z = vector
    return math.sqrt(x * x + y * y + z * z)


def normalize(vector: Iterable[float]) -> Tuple[float, float, float]:
    x, y, z = vector
    length = vector_length((x, y, z))
    if length == 0:
        raise ValueError("Cannot normalize a zero vector.")
    return (x / length, y / length, z / length)


def dot(a: Iterable[float], b: Iterable[float]) -> float:
    ax, ay, az = a
    bx, by, bz = b
    return ax * bx + ay * by + az * bz


def subtract(a: Iterable[float], b: Iterable[float]) -> Tuple[float, float, float]:
    ax, ay, az = a
    bx, by, bz = b
    return (ax - bx, ay - by, az - bz)


def add(a: Iterable[float], b: Iterable[float]) -> Tuple[float, float, float]:
    ax, ay, az = a
    bx, by, bz = b
    return (ax + bx, ay + by, az + bz)


def scale(vector: Iterable[float], factor: float) -> Tuple[float, float, float]:
    x, y, z = vector
    return (x * factor, y * factor, z * factor)
