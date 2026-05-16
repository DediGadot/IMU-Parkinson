"""Path and artifact facade for new code."""

from project_paths import (
    CACHE_DIR,
    DATA_DIR,
    FIGURES_DIR,
    REPO_ROOT,
    RESULTS_DIR,
    SPLIT_FILE,
    artifact_candidates,
    ensure_dir,
    ensure_parent,
    load_json_artifact,
    repo_artifact_path,
    results_artifact_path,
    save_json_artifact,
    save_text_artifact,
)

__all__ = [
    "CACHE_DIR",
    "DATA_DIR",
    "FIGURES_DIR",
    "REPO_ROOT",
    "RESULTS_DIR",
    "SPLIT_FILE",
    "artifact_candidates",
    "ensure_dir",
    "ensure_parent",
    "load_json_artifact",
    "repo_artifact_path",
    "results_artifact_path",
    "save_json_artifact",
    "save_text_artifact",
]

