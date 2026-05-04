import numpy as np
import pandas as pd
import sys
import types
from pathlib import Path
import pytest


def _import_run_baselines_with_mocks():
    # Mock a broad set of optional/heavy dependencies to allow safe import
    if 'lightgbm' not in sys.modules:
        mock_lgb = types.ModuleType('lightgbm')
        class _DummyLGBMRegressor:
            def __init__(self, *args, **kwargs):
                pass
            def fit(self, *args, **kwargs):
                return self
            def predict(self, *args, **kwargs):
                return []
        mock_lgb.LGBMRegressor = _DummyLGBMRegressor
        sys.modules['lightgbm'] = mock_lgb
    if 'xgboost' not in sys.modules:
        mock_xgb = types.ModuleType('xgboost')
        class _DummyXGBRegressor:
            def __init__(self, *args, **kwargs):
                pass
        mock_xgb.XGBRegressor = _DummyXGBRegressor
        mock_xgb.XGBRanker = type('DummyRanker', (), {})
        sys.modules['xgboost'] = mock_xgb
    if 'sklearn' not in sys.modules:
        mock_sklearn = types.ModuleType('sklearn')
        mock_sklearn.linear_model = types.ModuleType('sklearn.linear_model')
        class _DummyRidge:
            pass
        mock_sklearn.linear_model.Ridge = _DummyRidge
        mock_sklearn.linear_model.LinearRegression = type('DummyLR', (), {})
        sys.modules['sklearn'] = mock_sklearn
        sys.modules['sklearn.linear_model'] = mock_sklearn.linear_model
        mock_model_sel = types.ModuleType('sklearn.model_selection')
        mock_model_sel.StratifiedShuffleSplit = lambda *a, **k: None
        mock_model_sel.train_test_split = lambda *a, **k: ([], [])
        sys.modules['sklearn.model_selection'] = mock_model_sel
        mock_prep = types.ModuleType('sklearn.preprocessing')
        class StandardScaler:
            def fit(self, X, y=None):
                return self
            def transform(self, X):
                return X
        mock_prep.StandardScaler = StandardScaler
        sys.modules['sklearn.preprocessing'] = mock_prep
    # inductive_lib mock
    if 'inductive_lib' not in sys.modules:
        mock_il = types.ModuleType('inductive_lib')
        class _DummyFoldImputer:
            @staticmethod
            def fit(X):
                return X
        mock_il.FoldImputer = _DummyFoldImputer
        mock_il.full_metrics = lambda *a, **k: {"ccc": 0.0}
        mock_il.gen_5fold_split = lambda *a, **k: []
        sys.modules['inductive_lib'] = mock_il
    # project_paths mock
    if 'project_paths' not in sys.modules:
        mock_pp = types.ModuleType('project_paths')
        mock_pp.RESULTS_DIR = "/tmp/medical_results"
        mock_pp.results_artifact_path = lambda p: __import__('pathlib').Path(mock_pp.RESULTS_DIR) / p
        mock_pp.ensure_dir = lambda p: None
        sys.modules['project_paths'] = mock_pp
    # run_inductive_ablation mock
    if 'run_inductive_ablation' not in sys.modules:
        mock_ri = types.ModuleType('run_inductive_ablation')
        mock_ri.DEFAULT_LGB_PARAMS = {}
        mock_ri.SEEDS = [0, 1, 2]
        mock_ri.TARGET_CLIP = {"t1": (0.0, 1.0), "t2": (0.0, 1.0), "t3": (0.0, 1.0)}
        mock_ri._group_from_sid = lambda sid: sid
        mock_ri.feature_select = lambda Xd, yd, cols, k: (list(range(min(int(k), Xd.shape[1]))), None)
        mock_ri.load_features_and_targets = lambda: (pd.DataFrame({"sid": ["S1"]}), None, [])
        mock_ri.train_lgb = lambda Xd, yd, Xt, s: np.zeros(Xt.shape[0])
        sys.modules['run_inductive_ablation'] = mock_ri
    import importlib
    rb = importlib.import_module('run_baselines')
    return rb


rb = _import_run_baselines_with_mocks()


def test_get_features_v2_plus_variability_concatenation(monkeypatch):
    # Prepare a minimal pd_merged frame with V2 features and a FM feature
    df = pd.DataFrame({
        "sid": ["S1", "S2"],
        "v2_feat1": [0.5, 1.5],
        "v2_feat2": [2.0, 3.0],
        "fm_theta": [0.1, 0.2],  # FM feature should be ignored by V2_PLUS_VAR
    })
    # Do not include 'sid' in the feature_cols to avoid float-conversion errors
    feature_cols = ["v2_feat1", "v2_feat2", "fm_theta"]

    # Patch variability loader to return a deterministic array
    def fake_load_variability_features(sid_subset=None):
        X_var = np.array([[8.0, 16.0], [32.0, 64.0]], dtype=np.float32)
        var_cols = ["varA", "varB"]
        return X_var, var_cols

    monkeypatch.setattr(rb, "load_variability_features", fake_load_variability_features)

    X = rb._get_features(df, feature_cols, "V2_PLUS_VAR")

    expected = np.array(
        [
            [0.5, 2.0, 8.0, 16.0],
            [1.5, 3.0, 32.0, 64.0],
        ],
        dtype=np.float32,
    )

    assert X.shape == expected.shape
    assert np.allclose(X, expected)


def test_base7_entry_exists_and_defaults():
    # Ensure B7 baseline is present and immutable configuration matches code
    entry = rb.BASELINES.get("B7_v2_plus_variability")
    assert entry is not None
    feat_kind, predict_fn, kwargs = entry
    assert feat_kind == "V2_PLUS_VAR"
    assert callable(predict_fn)
    assert isinstance(kwargs, dict)
    # k should be 500 as defined in the module
    assert kwargs.get("k") == 500


def test_load_variability_features_exact_columns_and_values(tmp_path, monkeypatch):
    # Create tmp_path/ablation_v3_features.csv with header and rows
    csv_path = tmp_path / "ablation_v3_features.csv"
    csv_path.write_text(
        "sid,nl_feat1,sv_feat2,pa_feat3,fq_feat4,hr_feat5,ext_bad,ix_bad\n"
        "S1,0.1,0.2,0.3,0.4,0.5,9.9,8.8\n"
        "S2,1.1,1.2,1.3,1.4,1.5,7.7,6.6\n"
    )
    # Monkeypatch results_artifact_path to return the CSV
    monkeypatch.setattr(rb, "results_artifact_path", lambda p: csv_path)

    X, cols = rb.load_variability_features(["S2", "S1"])

    # Assert exact columns in correct order
    assert cols == ["nl_feat1", "sv_feat2", "pa_feat3", "fq_feat4", "hr_feat5"]
    # Assert numeric array matches expected values (S2 first, then S1)
    expected = np.array(
        [[1.1, 1.2, 1.3, 1.4, 1.5], [0.1, 0.2, 0.3, 0.4, 0.5]],
        dtype=np.float32,
    )
    assert X.shape == expected.shape
    assert np.allclose(X, expected)


def test_load_variability_features_excludes_ext_ix_columns(tmp_path, monkeypatch):
    # Create CSV with ext_ and ix_ prefixed columns
    csv_path = tmp_path / "ablation_v3_features.csv"
    csv_path.write_text(
        "sid,nl_feat1,sv_feat2,pa_feat3,fq_feat4,hr_feat5,ext_bad,ix_bad\n"
        "S1,0.1,0.2,0.3,0.4,0.5,9.9,8.8\n"
    )
    monkeypatch.setattr(rb, "results_artifact_path", lambda p: csv_path)

    X, cols = rb.load_variability_features(["S1"])

    # Verify no column starts with ext_ or ix_
    for col in cols:
        assert not col.startswith("ext_"), f"Column {col} should not be returned"
        assert not col.startswith("ix_"), f"Column {col} should not be returned"


def test_load_variability_features_missing_sid_raises_keyerror(tmp_path, monkeypatch):
    # Create CSV with only S1
    csv_path = tmp_path / "ablation_v3_features.csv"
    csv_path.write_text(
        "sid,nl_feat1,sv_feat2,pa_feat3,fq_feat4,hr_feat5\n"
        "S1,0.1,0.2,0.3,0.4,0.5\n"
    )
    monkeypatch.setattr(rb, "results_artifact_path", lambda p: csv_path)

    with pytest.raises(KeyError, match="Requested SIDs missing"):
        rb.load_variability_features(["S1", "S2"])
