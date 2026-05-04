import sys
import json
from pathlib import Path
import importlib
import types
import pandas as pd
import pytest


def _setup_stub_modules(tmp_results_dir: Path):
    # inductive_lib stub
    inductive_lib = types.ModuleType("inductive_lib")
    class DummyFoldImputer: pass
    inductive_lib.FoldImputer = DummyFoldImputer
    inductive_lib.full_metrics = lambda y_true, y_pred, label=None: {"ccc": 0.0}
    inductive_lib.gen_5fold_split = lambda *args, **kwargs: iter(())
    inductive_lib.run_null_test_gate = lambda *args, **kwargs: {}
    sys.modules["inductive_lib"] = inductive_lib

    # project_paths stub
    project_paths = types.ModuleType("project_paths")
    project_paths.RESULTS_DIR = tmp_results_dir
    project_paths.ensure_dir = lambda p: Path(p).mkdir(parents=True, exist_ok=True)
    project_paths.results_artifact_path = lambda name: tmp_results_dir / name
    sys.modules["project_paths"] = project_paths

    # run_inductive_ablation stub
    ria = types.ModuleType("run_inductive_ablation")
    ria.DEFAULT_LGB_PARAMS = {}
    ria.RECORDING_CACHE = ""
    ria.SEEDS = [0, 1, 2]
    ria.V2_CACHE = ""
    ria.TARGET_CLIP = {"t1": (0, 1), "t2": (0, 1), "t3": (0, 1)}
    ria._group_from_sid = lambda sid: "PD" if str(sid).startswith("PD") else "HC"
    ria.feature_select = lambda Xd, yd, idxs, k=None: (list(range(min(k or Xd.shape[1], Xd.shape[1]))), None)
    ria.load_features_and_targets = lambda *args, **kwargs: (None, None, [])
    ria.train_lgb = lambda *args, **kwargs: 0
    sys.modules["run_inductive_ablation"] = ria

    # run_calibration_v2 stub
    rc = types.ModuleType("run_calibration_v2")
    rc.compute_target = lambda item_scores, sid, t: 0.5
    rc.parse_per_item_scores = lambda: {}
    sys.modules["run_calibration_v2"] = rc

    # lightgbm stub
    lg = types.ModuleType("lightgbm")
    class DummyLGBMRegressor:
        def __init__(self, *args, **kwargs):
            pass
        def fit(self, *args, **kwargs):
            pass
        def predict(self, *args, **kwargs):
            return [0.0]
    lg.LGBMRegressor = DummyLGBMRegressor
    sys.modules["lightgbm"] = lg

    # xgboost stub
    xb = types.ModuleType("xgboost")
    class DummyXGBRegressor:
        def __init__(self, *args, **kwargs):
            pass
    xb.XGBRegressor = DummyXGBRegressor
    sys.modules["xgboost"] = xb

    # numpy/pandas are real libs in env; ensure pandas exists
    sys.modules["numpy"] = __import__("numpy")


def test_b7_loader_uses_v2_only_and_skips_fm_loader(tmp_path, monkeypatch):
    # Prepare stub environment and import rb with stubs
    _setup_stub_modules(tmp_path)
    # Ensure a clean import so we use the stubbed modules
    if "run_baselines" in sys.modules:
        del sys.modules["run_baselines"]
    rb = importlib.import_module("run_baselines")
    # Patch the loader and runner functions
    calls = {"v2": 0}
    def fake_load_v2_only_data():
        calls["v2"] += 1
        df = pd.DataFrame({"sid": ["WPD_TEST_1"], "updrs3": [1.0]})
        return df, ["sid", "updrs3"]
    def fail_if_called(*args, **kwargs):
        pytest.fail("load_features_and_targets should not be called for B7 path")
    def fake_run_baseline_5fold(pd_merged, feature_cols, target_key, baseline_id):
        return {"ccc": 0.123, "cal_slope": 0.456, "mae": 7.89, "runtime_s": 0.5}
    monkeypatch.setattr(rb, "load_v2_only_data", fake_load_v2_only_data, raising=True)
    monkeypatch.setattr(rb, "load_features_and_targets", fail_if_called, raising=True)
    monkeypatch.setattr(rb, "run_baseline_5fold", fake_run_baseline_5fold, raising=True)
    monkeypatch.setattr(sys, "argv", ["run_baselines.py", "--baseline", "B7_v2_plus_variability", "--target", "t3"])

    rb.main()
    assert calls["v2"] == 1
    out_path = rb.RESULTS_DIR / "baseline_B7_v2_plus_variability_t3_5split.json"
    assert out_path.exists()
    with open(out_path) as f:
        data = json.load(f)
    assert data.get("ccc") == 0.123
    out_path.unlink()


def test_non_b7_loader_calls_features_and_targets(tmp_path, monkeypatch):
    _setup_stub_modules(tmp_path)
    if "run_baselines" in sys.modules:
        del sys.modules["run_baselines"]
    rb = importlib.import_module("run_baselines")
    calls = {"feat": 0, "v2": 0}
    def fake_load_features_and_targets():
        calls["feat"] += 1
        df = pd.DataFrame({"sid": ["WPD_TEST_2"], "updrs3": [0.5]})
        return df, df, ["fm_example"]
    def fake_run_baseline_5fold(pd_merged, feature_cols, target_key, baseline_id):
        return {"ccc": 0.234, "cal_slope": 0.567, "mae": 8.88, "runtime_s": 0.6}
    monkeypatch.setattr(rb, "load_v2_only_data", lambda: (_ for _ in ()).throw(AssertionError("V2 loader should not be called for non-B7 path")), raising=True)
    monkeypatch.setattr(rb, "load_features_and_targets", fake_load_features_and_targets, raising=True)
    monkeypatch.setattr(rb, "run_baseline_5fold", fake_run_baseline_5fold, raising=True)
    monkeypatch.setattr(sys, "argv", ["run_baselines.py", "--baseline", "B0_null_mean", "--target", "t1"])
    rb.main()
    assert calls["feat"] == 1
    out_path = rb.RESULTS_DIR / "baseline_B0_null_mean_t1_5split.json"
    assert out_path.exists()
    with open(out_path) as f:
        data = json.load(f)
    assert data.get("ccc") == 0.234
    out_path.unlink()
