"""Tests for project_paths.py — artifact management and path resolution."""
import json
import os
import pytest
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def temp_repo(tmp_path):
    """Create a temporary repo structure for isolated path testing."""
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    return tmp_path, results_dir


class TestEnsureDir:
    def test_creates_directory(self, tmp_path):
        from project_paths import ensure_dir
        target = tmp_path / "new_dir" / "sub"
        result = ensure_dir(target)
        assert target.exists()
        assert target.is_dir()
        assert result == target

    def test_idempotent(self, tmp_path):
        from project_paths import ensure_dir
        target = tmp_path / "existing"
        target.mkdir()
        result = ensure_dir(target)  # should not raise
        assert result == target


class TestEnsureParent:
    def test_creates_parent_directory(self, tmp_path):
        from project_paths import ensure_parent
        target = tmp_path / "new_dir" / "file.json"
        result = ensure_parent(target)
        assert target.parent.exists()
        assert result == target

    def test_works_when_parent_exists(self, tmp_path):
        from project_paths import ensure_parent
        target = tmp_path / "file.json"
        result = ensure_parent(target)
        assert result == target


class TestSaveJsonArtifact:
    def test_saves_to_results(self, tmp_path, monkeypatch):
        from project_paths import save_json_artifact, RESULTS_DIR, ensure_dir
        ensure_dir(RESULTS_DIR)
        payload = {"test": True, "value": 42}
        paths = save_json_artifact("test_artifact.json", payload)
        assert len(paths) >= 1
        content = json.loads(paths[0].read_text())
        assert content["test"] is True
        assert content["value"] == 42
        # Cleanup
        paths[0].unlink()

    def test_saves_with_mirror(self, tmp_path, monkeypatch):
        from project_paths import save_json_artifact, RESULTS_DIR, REPO_ROOT, ensure_dir
        ensure_dir(RESULTS_DIR)
        payload = {"mirrored": True}
        paths = save_json_artifact("test_mirror.json", payload, mirror_root=True)
        assert len(paths) == 2
        for p in paths:
            content = json.loads(p.read_text())
            assert content["mirrored"] is True
            p.unlink()

    def test_pretty_prints_json(self):
        from project_paths import save_json_artifact, RESULTS_DIR, ensure_dir
        ensure_dir(RESULTS_DIR)
        payload = {"key": "val"}
        paths = save_json_artifact("test_pretty.json", payload)
        text = paths[0].read_text()
        assert "\n" in text  # indented
        assert text.endswith("\n")  # trailing newline
        paths[0].unlink()

    def test_handles_non_serializable_with_default_str(self):
        from project_paths import save_json_artifact, RESULTS_DIR, ensure_dir
        ensure_dir(RESULTS_DIR)
        payload = {"path": Path("/some/path")}
        paths = save_json_artifact("test_path_ser.json", payload)
        content = json.loads(paths[0].read_text())
        assert content["path"] == "/some/path"
        paths[0].unlink()


class TestSaveTextArtifact:
    def test_saves_text(self):
        from project_paths import save_text_artifact, RESULTS_DIR, ensure_dir
        ensure_dir(RESULTS_DIR)
        paths = save_text_artifact("test_text.txt", "hello world")
        assert paths[0].read_text() == "hello world"
        paths[0].unlink()


class TestLoadJsonArtifact:
    def test_loads_from_results(self):
        from project_paths import save_json_artifact, load_json_artifact, RESULTS_DIR, ensure_dir
        ensure_dir(RESULTS_DIR)
        payload = {"loaded": True}
        save_json_artifact("test_load.json", payload)
        data, path = load_json_artifact("test_load.json")
        assert data["loaded"] is True
        path.unlink()

    def test_raises_on_missing(self):
        from project_paths import load_json_artifact
        with pytest.raises(FileNotFoundError):
            load_json_artifact("nonexistent_artifact_xyz.json")


class TestArtifactCandidates:
    def test_returns_two_candidates(self):
        from project_paths import artifact_candidates
        result = artifact_candidates("some_file.json")
        assert len(result) == 2
        assert all(isinstance(p, Path) for p in result)


class TestConstants:
    def test_repo_root_exists(self):
        from project_paths import REPO_ROOT
        assert REPO_ROOT.exists()
        assert REPO_ROOT.is_dir()

    def test_results_dir_is_path(self):
        from project_paths import RESULTS_DIR
        assert isinstance(RESULTS_DIR, Path)

    def test_data_dir_is_path(self):
        from project_paths import DATA_DIR
        assert isinstance(DATA_DIR, Path)

    def test_split_file_is_path(self):
        from project_paths import SPLIT_FILE
        assert isinstance(SPLIT_FILE, Path)


class TestResolveDataDir:
    def test_env_override(self):
        """WEARGAIT_DATA_DIR env var should override auto-detection."""
        from project_paths import _resolve_data_dir
        with patch.dict(os.environ, {"WEARGAIT_DATA_DIR": "/tmp/fake_data"}):
            result = _resolve_data_dir()
            assert result == Path("/tmp/fake_data")

    def test_returns_path_object(self):
        from project_paths import _resolve_data_dir
        result = _resolve_data_dir()
        assert isinstance(result, Path)
