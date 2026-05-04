import numpy as np
import pandas as pd
import sys
import types
import pytest


# Stub import pattern matching tests/test_run_baselines_variability.py
def _import_run_baselines_with_mocks():
    # Mock heavy dependencies that run_baselines imports at module load
    if 'lightgbm' not in sys.modules:
        mock_lgb = types.ModuleType('lightgbm')
        class _DummyLGBMRegressor:
            def __init__(self, *args, **kwargs):
                pass
            def fit(self, *args, **kwargs):
                return self
            def predict(self, *args, **kwargs):
                return []
        mock_lgb.__b7_null_gate_test_mock__ = True
        mock_lgb.LGBMRegressor = _DummyLGBMRegressor
        sys.modules['lightgbm'] = mock_lgb
    if 'xgboost' not in sys.modules:
        mock_xgb = types.ModuleType('xgboost')
        class _DummyXGBRegressor:
            def __init__(self, *args, **kwargs):
                pass
        mock_xgb.XGBRegressor = _DummyXGBRegressor
        mock_xgb.XGBRanker = type('DummyRanker', (), {})
        mock_xgb.__b7_null_gate_test_mock__ = True
        sys.modules['xgboost'] = mock_xgb
    if 'sklearn' not in sys.modules:
        mock_sklearn = types.ModuleType('sklearn')
        mock_sklearn.__b7_null_gate_test_mock__ = True
        mock_sklearn.linear_model = types.ModuleType('sklearn.linear_model')
        mock_sklearn.linear_model.__b7_null_gate_test_mock__ = True
        class _DummyRidge:
            pass
        mock_sklearn.linear_model.Ridge = _DummyRidge
        mock_sklearn.linear_model.LinearRegression = type('DummyLR', (), {})
        sys.modules['sklearn'] = mock_sklearn
        sys.modules['sklearn.linear_model'] = mock_sklearn.linear_model
        mock_model_sel = types.ModuleType('sklearn.model_selection')
        mock_model_sel.__b7_null_gate_test_mock__ = True
        mock_model_sel.StratifiedShuffleSplit = lambda *a, **k: None
        mock_model_sel.train_test_split = lambda *a, **k: ([], [])
        sys.modules['sklearn.model_selection'] = mock_model_sel
        mock_prep = types.ModuleType('sklearn.preprocessing')
        mock_prep.__b7_null_gate_test_mock__ = True
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
        mock_il.__b7_null_gate_test_mock__ = True
        class _DummyFoldImputer:
            @staticmethod
            def fit(X):
                return X
        mock_il.FoldImputer = _DummyFoldImputer
        mock_il.full_metrics = lambda *a, **k: {"ccc": 0.0}
        mock_il.gen_5fold_split = lambda *a, **k: []
        mock_il.run_null_test_gate = lambda *a, **k: {}
        sys.modules['inductive_lib'] = mock_il
    # project_paths mock
    if 'project_paths' not in sys.modules:
        mock_pp = types.ModuleType('project_paths')
        mock_pp.__b7_null_gate_test_mock__ = True
        mock_pp.RESULTS_DIR = "/tmp/medical_results"
        mock_pp.results_artifact_path = lambda p: __import__('pathlib').Path(mock_pp.RESULTS_DIR) / p
        mock_pp.ensure_dir = lambda p: None
        sys.modules['project_paths'] = mock_pp
    # run_inductive_ablation mock
    if 'run_inductive_ablation' not in sys.modules:
        mock_ri = types.ModuleType('run_inductive_ablation')
        mock_ri.__b7_null_gate_test_mock__ = True
        mock_ri.DEFAULT_LGB_PARAMS = {}
        mock_ri.RECORDING_CACHE = __import__('pathlib').Path('/tmp/mock_recording_cache.npz')
        mock_ri.V2_CACHE = __import__('pathlib').Path('/tmp/mock_v2_cache.csv')
        mock_ri.SEEDS = [0, 1, 2]
        mock_ri.TARGET_CLIP = {"t1": (0, 24), "t2": (0, 32), "t3": (0, 59)}
        mock_ri._group_from_sid = lambda sid: sid
        mock_ri.feature_select = lambda Xd, yd, cols, k: (list(range(min(int(k), Xd.shape[1]))), None)
        mock_ri.load_features_and_targets = lambda: (pd.DataFrame({"sid": ["S1"]}), None, [])
        mock_ri.train_lgb = lambda Xd, yd, Xt, s: np.zeros(Xt.shape[0])
        mock_ri.compute_target = lambda *a, **k: 0.0
        mock_ri.parse_per_item_scores = lambda *a, **k: {}
        sys.modules['run_inductive_ablation'] = mock_ri
    # run_calibration_v2 mock
    if 'run_calibration_v2' not in sys.modules:
        mock_rc = types.ModuleType('run_calibration_v2')
        mock_rc.__b7_null_gate_test_mock__ = True
        mock_rc.compute_target = lambda *a, **k: 0.0
        mock_rc.parse_per_item_scores = lambda *a, **k: {}
        sys.modules['run_calibration_v2'] = mock_rc
    import importlib
    mod = importlib.import_module('run_baselines')
    # The import-time mocks above are only for this test module's `rb` handle.
    # Remove them from sys.modules so other test modules import the real project
    # implementations during collection/execution.
    for name in [
        'lightgbm', 'xgboost',
        'sklearn', 'sklearn.linear_model', 'sklearn.model_selection', 'sklearn.preprocessing',
        'inductive_lib', 'project_paths', 'run_inductive_ablation', 'run_calibration_v2',
    ]:
        if getattr(sys.modules.get(name), '__b7_null_gate_test_mock__', False):
            del sys.modules[name]
    return mod


rb = _import_run_baselines_with_mocks()


@pytest.fixture
def sample_pd_merged():
    """Build helper DataFrame with S1-S4 subjects."""
    return pd.DataFrame({
        "sid": ["S1", "S2", "S3", "S4"],
        "t3_target": [10.0, 20.0, 30.0, 40.0],
        "v2_a": [1.0, 2.0, 3.0, 4.0],
        "v2_b": [0.1, 0.2, 0.3, 0.4],
    })


@pytest.fixture
def feature_cols():
    return ["v2_a", "v2_b"]


class TestRejectsInvalidConfigs:
    def test_non_b7_baseline_raises(self, sample_pd_merged, feature_cols):
        with pytest.raises(ValueError, match="Null-gate validation only supports"):
            rb.run_null_gate_validation(
                pd_merged=sample_pd_merged,
                feature_cols=feature_cols,
                target_key="t3",
                baseline_id="SCRAMBLED",  # Not B7
            )

    def test_target_all_raises(self, sample_pd_merged, feature_cols):
        with pytest.raises(ValueError, match="does not support target='all'"):
            rb.run_null_gate_validation(
                pd_merged=sample_pd_merged,
                feature_cols=feature_cols,
                target_key="all",
                baseline_id="B7_v2_plus_variability",
            )

    def test_overlapping_split_raises(self, sample_pd_merged, feature_cols, monkeypatch):
        # Mock _get_features to return deterministic matrix and avoid external cache lookups
        def fake_get_features(pd_merged, feature_cols, kind):
            return pd_merged[feature_cols].values.astype(np.float32)

        monkeypatch.setattr(rb, "_get_features", fake_get_features)

        # Force overlapping fold by mocking gen_5fold_split
        def fake_split(pd_merged, target_key):
            # Both train and test contain S1 -> overlap
            yield 1, ["S1", "S2"], ["S1", "S3"]

        monkeypatch.setattr(rb, "gen_5fold_split", fake_split)

        with pytest.raises(ValueError, match="non-empty SID overlap"):
            rb.run_null_gate_validation(
                pd_merged=sample_pd_merged,
                feature_cols=feature_cols,
                target_key="t3",
                baseline_id="B7_v2_plus_variability",
            )


class TestRunNullTestGateInvocation:
    def test_called_once_for_one_fold(self, sample_pd_merged, feature_cols, monkeypatch):
        # Track calls to run_null_test_gate
        calls = []

        def fake_run_null_test_gate(predict_fn, X_train, y_train, X_test, y_test, train_sids=None, test_sid=None):
            calls.append({
                "X_test_shape": X_test.shape,
                "X_train_shape": X_train.shape,
                "train_sids": train_sids,
                "test_sid": test_sid,
            })
            return {"scrambled_label_ccc": 0.0, "canary_feature_ccc": 0.0}

        monkeypatch.setattr(rb, "run_null_test_gate", fake_run_null_test_gate)

        # Mock _get_features to return deterministic 4x2 matrix
        def fake_get_features(pd_merged, feature_cols, kind):
            return pd_merged[feature_cols].values.astype(np.float32)

        monkeypatch.setattr(rb, "_get_features", fake_get_features)

        # Force 1-fold split
        def fake_split(pd_merged, target_key):
            yield 1, ["S1", "S2"], ["S3", "S4"]

        monkeypatch.setattr(rb, "gen_5fold_split", fake_split)

        rb.run_null_gate_validation(
            pd_merged=sample_pd_merged,
            feature_cols=feature_cols,
            target_key="t3",
            baseline_id="B7_v2_plus_variability",
        )

        # Verify run_null_test_gate called once (one fold)
        assert len(calls) == 1, f"Expected 1 call, got {len(calls)}"

        # Verify receives all fold test rows (2 rows for fold with S3, S4)
        assert calls[0]["X_test_shape"][0] == 2, "Expected 2 test rows (all fold test SIDs)"


class TestB7PredictorWrapper:
    def test_b7_baseline_uses_v2_plus_var_features(self, sample_pd_merged, feature_cols, monkeypatch):
        # Verify B7_v2_plus_variability uses V2_PLUS_VAR feature kind
        # The baseline lookup should return V2_PLUS_VAR for feat_kind
        feat_kind, _, _ = rb.BASELINES["B7_v2_plus_variability"]
        assert feat_kind == "V2_PLUS_VAR", f"Expected V2_PLUS_VAR, got {feat_kind}"

        # Also verify it has k=500 in kwargs
        _, _, kwargs = rb.BASELINES["B7_v2_plus_variability"]
        assert kwargs.get("k") == 500, f"Expected k=500, got {kwargs.get('k')}"

    def test_b7_predictor_passes_k_and_clip(self, sample_pd_merged, feature_cols, monkeypatch):
        # Capture k and clip values from predict_fn invocation
        captured = {}

        def fake_predict_fn(X_train, y_train, X_test, k=None, clip=None, **kw):
            # Capture the k and clip values passed to predict_fn
            captured["k"] = k
            captured["clip"] = clip
            # Return a constant prediction vector matching X_test shape
            return np.zeros(X_test.shape[0])

        # Replace B7 baseline entry with fake_predict_fn that captures k and clip
        orig_entry = rb.BASELINES["B7_v2_plus_variability"]
        feat_kind, _, kwargs = orig_entry
        rb.BASELINES["B7_v2_plus_variability"] = (feat_kind, fake_predict_fn, kwargs)

        # Create X, y arrays matching sample_pd_merged
        X = sample_pd_merged[feature_cols].values.astype(np.float32)
        y = sample_pd_merged["t3_target"].values.astype(np.float32)

        # Manually construct what run_null_gate_validation does:
        # 1. Get baseline entry
        feat_kind, predict_fn, kwargs = rb.BASELINES["B7_v2_plus_variability"]
        # 2. Get clip for t3 target
        clip = rb.TARGET_CLIP["t3"]
        # 3. Define b7_predictor wrapper (as in run_null_gate_validation)
        def b7_predictor(X_train, y_train, X_test):
            return predict_fn(X_train, y_train, X_test, clip=clip, **kwargs)
        # 4. Call the wrapper
        b7_predictor(X[:2], y[:2], X[2:])

        # Verify captured k and clip values
        assert captured.get("k") == 500, f"Expected k=500, got {captured.get('k')}"
        assert captured.get("clip") == rb.TARGET_CLIP["t3"], f"Expected clip={rb.TARGET_CLIP['t3']}, got {captured.get('clip')}"


class TestUnsupportedChecks:
    def test_unsupported_checks_present(self, sample_pd_merged, feature_cols, monkeypatch):
        # Need to actually invoke run_null_gate_validation to get unsupported_checks in result
        def fake_split(pd_merged, target_key):
            yield 1, ["S1", "S2"], ["S3", "S4"]

        monkeypatch.setattr(rb, "gen_5fold_split", fake_split)

        def fake_get_features(pd_merged, feature_cols, kind):
            return pd_merged[feature_cols].values.astype(np.float32)

        monkeypatch.setattr(rb, "_get_features", fake_get_features)

        def fake_run_null_test_gate(predict_fn, X_train, y_train, X_test, y_test, **kw):
            return {"scrambled_label_ccc": 0.0, "canary_feature_ccc": 0.0}

        monkeypatch.setattr(rb, "run_null_test_gate", fake_run_null_test_gate)

        result = rb.run_null_gate_validation(
            pd_merged=sample_pd_merged,
            feature_cols=feature_cols,
            target_key="t3",
            baseline_id="B7_v2_plus_variability",
        )

        unsupported = result.get("unsupported_checks", {})
        assert "subject_id_shuffle" in unsupported, "Missing subject_id_shuffle"
        assert "library_exclusion" in unsupported, "Missing library_exclusion"
        assert "transductive_sanity" in unsupported, "Missing transductive_sanity"


class TestAggregationMetrics:
    def test_averages_two_folds(self, sample_pd_merged, feature_cols, monkeypatch):
        # Mock two folds returning different CCCs
        fold_results = [
            {"scrambled_label_ccc": 0.1, "canary_feature_ccc": 0.2},
            {"scrambled_label_ccc": 0.3, "canary_feature_ccc": 0.4},
        ]

        call_count = [0]

        def fake_run_null_test_gate(predict_fn, X_train, y_train, X_test, y_test, **kw):
            res = fold_results[call_count[0]]
            call_count[0] += 1
            return res

        monkeypatch.setattr(rb, "run_null_test_gate", fake_run_null_test_gate)

        def fake_get_features(pd_merged, feature_cols, kind):
            return pd_merged[feature_cols].values.astype(np.float32)

        monkeypatch.setattr(rb, "_get_features", fake_get_features)

        def fake_split(pd_merged, target_key):
            yield 1, ["S1", "S2"], ["S3", "S4"]
            yield 2, ["S1", "S3"], ["S2", "S4"]

        monkeypatch.setattr(rb, "gen_5fold_split", fake_split)

        result = rb.run_null_gate_validation(
            pd_merged=sample_pd_merged,
            feature_cols=feature_cols,
            target_key="t3",
            baseline_id="B7_v2_plus_variability",
        )

        mean_scrambled = result.get("mean_scrambled_label_ccc")
        mean_canary = result.get("mean_canary_feature_ccc")

        # (0.1 + 0.3) / 2 = 0.2
        assert mean_scrambled == 0.2, f"Expected mean_scrambled=0.2, got {mean_scrambled}"
        # (0.2 + 0.4) / 2 = 0.3
        assert mean_canary == 0.3, f"Expected mean_canary=0.3, got {mean_canary}"