import sys
import types
import importlib
from pathlib import Path
import json
import numpy as np


def _make_dummy_sklearn_modules():
    # Create minimal stubs for sklearn Ridge to satisfy imports
    sklearn = types.ModuleType("sklearn")
    linear_model = types.ModuleType("sklearn.linear_model")
    class Ridge:
        def __init__(self, *args, **kwargs):
            pass
        def fit(self, X, y):
            return self
        def predict(self, X):
            return np.zeros(X.shape[0])
    linear_model.Ridge = Ridge
    sklearn.linear_model = linear_model
    sys.modules["sklearn"] = sklearn
    sys.modules["sklearn.linear_model"] = linear_model


def _setup_dummy_imports(tmp_results_dir: Path):
    # lightgbm stub
    lgb = types.ModuleType("lightgbm")
    class LGBMRegressor:
        def __init__(self, *args, **kwargs):
            pass
        def fit(self, X, y):
            return self
        def predict(self, X):
            return np.zeros(X.shape[0])
    lgb.LGBMRegressor = LGBMRegressor
    sys.modules["lightgbm"] = lgb

    # xgboost stub
    xgb = types.ModuleType("xgboost")
    class XGBRegressor:
        def __init__(self, *args, **kwargs):
            pass
        def fit(self, X, y):
            return self
        def predict(self, X):
            return np.zeros(X.shape[0])
    xgb.XGBRegressor = XGBRegressor
    sys.modules["xgboost"] = xgb

    _make_dummy_sklearn_modules()

    # inductive_lib stub
    ind_lib = types.ModuleType("inductive_lib")
    class FoldImputer:
        @staticmethod
        def fit(X):
            return FoldImputer()
        def transform(self, X):
            return X
    def full_metrics(true, pred, label=None):
        return {"ccc": 0.0, "cal_slope": 0.0, "mae": 0.0}
    def gen_5fold_split(pd_merged, target_key):
        yield ([], [], [])
    ind_lib.FoldImputer = FoldImputer
    ind_lib.full_metrics = full_metrics
    ind_lib.gen_5fold_split = gen_5fold_split
    sys.modules["inductive_lib"] = ind_lib

    # run_inductive_ablation stub
    ria = types.ModuleType("run_inductive_ablation")
    ria.DEFAULT_LGB_PARAMS = {"n_estimators": 100, "max_depth": 5, "objective": "regression", "colsample_bytree": 1.0, "subsample": 1.0, "reg_lambda": 0.0, "min_data_in_leaf": 20, "learnin g_rate": 0.1}
    ria.SEEDS = [0, 1, 2]
    ria.TARGET_CLIP = {"t1": (0.0, 24.0), "t2": (0.0, 24.0), "t3": (0.0, 24.0)}
    def _group_from_sid(sid):
        return 0
    def feature_select(Xd, yd, idx_list, k=1000):
        # simple passthrough selector
        return list(range(min(k, Xd.shape[1]))), None
    def load_features_and_targets():
        # Minimal stub; not used by adversarial tests
        import pandas as pd
        df = pd.DataFrame({"sid": ["s1"], "t1_target": [0.0]})
        return df, df, ["t1_target"]
    def train_lgb(Xd, yd, Xt, s):
        return np.zeros(Xt.shape[0])
    ria._group_from_sid = _group_from_sid
    ria.feature_select = feature_select
    ria.load_features_and_targets = load_features_and_targets
    ria.train_lgb = train_lgb
    sys.modules["run_inductive_ablation"] = ria

    # project_paths stub to direct artifacts to tmp dir
    pp = types.ModuleType("project_paths")
    pp.RESULTS_DIR = tmp_results_dir
    def ensure_dir(p: Path):
        p.mkdir(parents=True, exist_ok=True)
        return p
    pp.ensure_dir = ensure_dir
    def results_artifact_path(name: str) -> Path:
        return tmp_results_dir / name
    pp.results_artifact_path = results_artifact_path
    sys.modules["project_paths"] = pp


def _import_run_baselines(tmp_results_dir: Path):
    # Ensure we remove any cached module to force re-import with mocks
    if "run_baselines" in sys.modules:
        del sys.modules["run_baselines"]
    _setup_dummy_imports(tmp_results_dir)
    _setup_dummy_imports(tmp_results_dir)
    importlib.invalidate_caches()
    import run_baselines
    return run_baselines


def test_no_variability_columns_fails(tmp_path):
    # Prepare dummy imports and path
    run_baselines = _import_run_baselines(tmp_path)
    cache_path = tmp_path / "ablation_v3_features.csv"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    # Write header with no variability columns (only ext_ prefix)
    cache_path.write_text("sid,ext_x\n" + "s1,0\n")

    import pytest
    with pytest.raises(ValueError) as exc:
        run_baselines.load_variability_features()
    assert "No variability-prefix columns" in str(exc.value)


def test_duplicate_sid_in_subset_raises(tmp_path):
    run_baselines = _import_run_baselines(tmp_path)
    cache_path = tmp_path / "ablation_v3_features.csv"
    # header with one variability column
    cache_path.write_text("sid,nl_var\ns1,1.0\ns2,2.0\ns1,3.0\n")
    # sid_subset contains duplicates - should fail fast
    sid_subset = ["s1", "s2", "s1"]
    import pytest
    with pytest.raises(ValueError) as exc:
        run_baselines.load_variability_features(sid_subset)
    assert "Duplicate SIDs" in str(exc.value)


def test_missing_sid_in_subset_raises(tmp_path):
    run_baselines = _import_run_baselines(tmp_path)
    cache_path = tmp_path / "ablation_v3_features.csv"
    cache_path.write_text("sid,nl_var\ns1,0.5\ns2,0.6\n")
    import pytest
    with pytest.raises(KeyError) as exc:
        run_baselines.load_variability_features(["s1", "s3"])
    assert "Requested SIDs missing from cache" in str(exc.value)


def test_missing_sid_column_raises(tmp_path):
    run_baselines = _import_run_baselines(tmp_path)
    cache_path = tmp_path / "ablation_v3_features.csv"
    # header uses a non-sid column name; variability prefix present
    cache_path.write_text("sidX,nl_var\ns1,0.5\n")
    import pytest
    with pytest.raises(Exception):
        run_baselines.load_variability_features()


def test_empty_sid_subset_returns_empty(tmp_path):
    run_baselines = _import_run_baselines(tmp_path)
    cache_path = tmp_path / "ablation_v3_features.csv"
    cache_path.write_text("sid,nl_var\ns1,0.5\ns2,0.6\n")
    X, cols = run_baselines.load_variability_features([])
    assert X.shape == (0, 1)
    assert cols == ["nl_var"]
