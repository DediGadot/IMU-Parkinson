"""Shared path and artifact helpers for the WearGait-PD repo."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent
LEGACY_ROOT = Path("/root/pd-imu")

RESULTS_DIR = Path(os.getenv("WEARGAIT_RESULTS_DIR", REPO_ROOT / "results"))
FIGURES_DIR = Path(os.getenv("WEARGAIT_FIGURES_DIR", REPO_ROOT / "figures"))
CACHE_DIR = Path(os.getenv("WEARGAIT_CACHE_DIR", REPO_ROOT / "data" / "cache"))


def _resolve_data_dir() -> Path:
    env = os.getenv("WEARGAIT_DATA_DIR")
    if env:
        return Path(env)

    candidates = [
        REPO_ROOT / "data" / "raw" / "weargait-pd",
        LEGACY_ROOT / "data" / "raw" / "weargait-pd",
    ]
    for candidate in candidates:
        try:
            if candidate.exists():
                return candidate
        except OSError:
            continue
    return candidates[0]


DATA_DIR = _resolve_data_dir()
SPLIT_FILE = Path(os.getenv("WEARGAIT_SPLIT_FILE", RESULTS_DIR / "data_split.json"))


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def repo_artifact_path(name: str) -> Path:
    return REPO_ROOT / name


def results_artifact_path(name: str) -> Path:
    ensure_dir(RESULTS_DIR)
    return RESULTS_DIR / name


def artifact_candidates(name: str) -> list[Path]:
    return [results_artifact_path(name), repo_artifact_path(name)]


def load_json_artifact(name: str) -> tuple[Any, Path]:
    for path in artifact_candidates(name):
        if path.exists():
            return json.loads(path.read_text()), path
    raise FileNotFoundError(f"Artifact not found in repo root or results/: {name}")


def save_json_artifact(name: str, payload: Any, mirror_root: bool = False) -> list[Path]:
    targets = [results_artifact_path(name)]
    if mirror_root:
        targets.append(repo_artifact_path(name))

    for path in targets:
        ensure_parent(path)
        path.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    return targets


def save_text_artifact(name: str, text: str, mirror_root: bool = False) -> list[Path]:
    targets = [results_artifact_path(name)]
    if mirror_root:
        targets.append(repo_artifact_path(name))

    for path in targets:
        ensure_parent(path)
        path.write_text(text)
    return targets
