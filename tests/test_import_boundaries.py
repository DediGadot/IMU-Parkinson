from pathlib import Path

from audit_import_boundaries import collect_boundary_edges, collect_package_legacy_edges, compare_edges, edge_key


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_collect_boundary_edges_finds_non_exception_run_import(tmp_path):
    _write(tmp_path / "run_source.py", "from run_target import helper\n")
    _write(tmp_path / "run_target.py", "def helper():\n    return 1\n")

    edges = collect_boundary_edges(tmp_path)

    assert [edge["edge_key"] for edge in edges] == [edge_key("run_source.py", "run_target")]
    assert edges[0]["source_category"] == "experiment_runner"
    assert edges[0]["target_category"] == "experiment_runner"


def test_collect_boundary_edges_ignores_allowed_legacy_exception(tmp_path):
    _write(tmp_path / "run_clean_benchmark.py", "from run_ablation_v2 import helper\n")
    _write(tmp_path / "run_ablation_v2.py", "def helper():\n    return 1\n")

    assert collect_boundary_edges(tmp_path) == []


def test_compare_edges_flags_new_edges_against_baseline():
    current = [
        {
            "source": "run_new",
            "source_path": "run_new.py",
            "source_category": "experiment_runner",
            "target": "run_old",
            "target_path": "run_old.py",
            "target_category": "experiment_runner",
            "edge_key": edge_key("run_new.py", "run_old"),
        }
    ]
    baseline = {"edge_keys": []}

    comparison = compare_edges(current, baseline)

    assert comparison["new_edges"] == current


def test_compare_edges_accepts_grandfathered_edge():
    key = edge_key("run_new.py", "run_old")
    current = [
        {
            "source": "run_new",
            "source_path": "run_new.py",
            "source_category": "experiment_runner",
            "target": "run_old",
            "target_path": "run_old.py",
            "target_category": "experiment_runner",
            "edge_key": key,
        }
    ]
    baseline = {"edge_keys": [key]}

    comparison = compare_edges(current, baseline)

    assert comparison["new_edges"] == []
    assert comparison["removed_edge_keys"] == []


def test_collect_package_legacy_edges_flags_pd_imu_run_import(tmp_path):
    _write(tmp_path / "pd_imu" / "__init__.py", "")
    _write(tmp_path / "pd_imu" / "new_layer.py", "from run_target import helper\n")
    _write(tmp_path / "run_target.py", "def helper():\n    return 1\n")

    edges = collect_package_legacy_edges(tmp_path)

    assert [edge["edge_key"] for edge in edges] == [edge_key("pd_imu/new_layer.py", "run_target")]
    assert edges[0]["source_category"] == "architecture_facade"
    assert edges[0]["target_category"] == "experiment_runner"


def test_collect_package_legacy_edges_allows_explicit_legacy_shim(tmp_path):
    _write(tmp_path / "pd_imu" / "core" / "__init__.py", "")
    _write(
        tmp_path / "pd_imu" / "core" / "legacy_experiment_api.py",
        "from run_t1_iter4 import T1_ITEMS\n",
    )
    _write(tmp_path / "run_t1_iter4.py", "T1_ITEMS = (9, 10, 11, 12, 13, 14)\n")

    assert collect_package_legacy_edges(tmp_path) == []
