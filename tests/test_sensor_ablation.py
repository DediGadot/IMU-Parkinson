"""Tests for sensor ablation — feature filtering logic and config integrity."""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data_split import SENSORS
from run_sensor_ablation import filter_features_for_sensors, SENSOR_CONFIGS


# ── SENSOR_CONFIGS integrity ────────────────────────────────────────


class TestSensorConfigs:
    def test_all_13_has_all_sensors(self):
        assert set(SENSOR_CONFIGS["all_13"]) == set(SENSORS)
        assert len(SENSOR_CONFIGS["all_13"]) == 13

    def test_all_configs_use_valid_sensors(self):
        valid = set(SENSORS)
        for name, sensors in SENSOR_CONFIGS.items():
            invalid = set(sensors) - valid
            assert not invalid, f"Config '{name}' has invalid sensors: {invalid}"

    def test_leave_group_out_removes_exactly_one_group(self):
        full = set(SENSORS)
        for name, sensors in SENSOR_CONFIGS.items():
            if name.startswith("no_"):
                removed = full - set(sensors)
                assert len(removed) >= 1, f"Config '{name}' didn't remove any sensors"
                assert len(sensors) < 13, f"Config '{name}' should have fewer than 13 sensors"

    def test_clinical_subsets_nonempty(self):
        clinical = ["lower_back_1", "wrists_2", "back_wrists_3", "back_ankles_3",
                     "feet_ankles_4", "minimal_5", "lower_body_9", "upper_body_4"]
        for name in clinical:
            assert len(SENSOR_CONFIGS[name]) > 0

    def test_lower_back_1_is_single(self):
        assert SENSOR_CONFIGS["lower_back_1"] == ["LowerBack"]

    def test_wrists_2_correct(self):
        assert set(SENSOR_CONFIGS["wrists_2"]) == {"R_Wrist", "L_Wrist"}

    def test_minimal_5_correct(self):
        expected = {"LowerBack", "R_Wrist", "L_Wrist", "R_Ankle", "L_Ankle"}
        assert set(SENSOR_CONFIGS["minimal_5"]) == expected

    def test_no_duplicate_config_names(self):
        names = list(SENSOR_CONFIGS.keys())
        assert len(names) == len(set(names))


# ── filter_features_for_sensors ─────────────────────────────────────


class TestFilterFeaturesForSensors:
    """Test the core feature routing logic."""

    @pytest.fixture
    def sample_columns(self):
        """A realistic set of feature column names."""
        cols = []
        # Direct sensor features
        for s in SENSORS:
            cols.extend([
                f"{s}_Acc_X_rms", f"{s}_Acc_Y_std", f"{s}_Gyr_Z_skew",
            ])
        # Asymmetry features
        cols.extend([
            "asy_Wrist_rms_diff", "asy_Wrist_std_ratio",
            "asy_Ankle_rms_diff", "asy_DorsalFoot_gyr_diff",
        ])
        # Event/turn features (derived from LowerBack)
        cols.extend(["ev_walk_count", "ev_turn_mean", "trn_duration", "sts_rise_time", "bal_sway"])
        # Foot contact features
        cols.extend(["fc_stride_time", "fc_stance_ratio", "fc_double_support"])
        # Kinematics
        cols.extend(["k_R_angle_mean", "k_L_angle_std"])
        # Distribution/contrast features
        cols.extend([
            "dv_LowerBack_Acc_X_var", "dv_R_Wrist_Gyr_Z_iqr",
            "d_LowerBack_pace_ratio", "r_R_Ankle_contrast",
        ])
        # Covariates
        cols.extend(["cv_age", "cv_sex", "cv_ht", "cv_wt", "cv_yrs", "cv_dbs"])
        # Extended covariates
        cols.extend(["ext_height", "ext_weight", "ext_bmi"])
        # Distilled walkway
        cols.extend(["dst_stride_proxy", "dst_cadence_proxy"])
        # Metadata
        cols.extend(["n_recordings", "duration_s"])
        return cols

    def test_all_13_keeps_everything_except_dst(self, sample_columns):
        result = filter_features_for_sensors(sample_columns, SENSORS, allow_privileged_dst=False)
        assert "dst_stride_proxy" not in result
        assert "dst_cadence_proxy" not in result
        # All non-dst should be kept
        non_dst = [c for c in sample_columns if not c.startswith("dst_")]
        assert set(non_dst) == set(result)

    def test_all_13_keeps_dst_when_allowed(self, sample_columns):
        result = filter_features_for_sensors(sample_columns, SENSORS, allow_privileged_dst=True)
        assert "dst_stride_proxy" in result
        assert "dst_cadence_proxy" in result

    def test_sensor_prefix_filtering(self, sample_columns):
        """Only features from included sensors should survive."""
        result = filter_features_for_sensors(sample_columns, ["LowerBack"])
        # LowerBack features should be present
        lb_feats = [c for c in result if c.startswith("LowerBack_")]
        assert len(lb_feats) > 0
        # Other sensor features should be absent
        rw_feats = [c for c in result if c.startswith("R_Wrist_")]
        assert len(rw_feats) == 0

    def test_asymmetry_requires_both_sides(self, sample_columns):
        """Asymmetry features need both L and R of the pair."""
        # Only R_Wrist, no L_Wrist → asy_Wrist_ should be excluded
        result = filter_features_for_sensors(sample_columns, ["R_Wrist"])
        wrist_asy = [c for c in result if c.startswith("asy_Wrist")]
        assert len(wrist_asy) == 0

        # Both wrists → asy_Wrist_ should be included
        result2 = filter_features_for_sensors(sample_columns, ["R_Wrist", "L_Wrist"])
        wrist_asy2 = [c for c in result2 if c.startswith("asy_Wrist")]
        assert len(wrist_asy2) > 0

    def test_event_features_require_lowerback(self, sample_columns):
        """ev_, trn_, sts_, bal_ features derived from LowerBack."""
        result = filter_features_for_sensors(sample_columns, ["R_Wrist"])
        event_feats = [c for c in result if c.startswith(("ev_", "trn_", "sts_", "bal_"))]
        assert len(event_feats) == 0

        result2 = filter_features_for_sensors(sample_columns, ["LowerBack"])
        event_feats2 = [c for c in result2 if c.startswith(("ev_", "trn_", "sts_", "bal_"))]
        assert len(event_feats2) > 0

    def test_foot_contact_requires_foot_or_ankle(self, sample_columns):
        """fc_ features need foot or ankle sensors."""
        result = filter_features_for_sensors(sample_columns, ["LowerBack"])
        fc_feats = [c for c in result if c.startswith("fc_")]
        assert len(fc_feats) == 0

        result2 = filter_features_for_sensors(sample_columns, ["R_Ankle"])
        fc_feats2 = [c for c in result2 if c.startswith("fc_")]
        assert len(fc_feats2) > 0

        result3 = filter_features_for_sensors(sample_columns, ["R_DorsalFoot"])
        fc_feats3 = [c for c in result3 if c.startswith("fc_")]
        assert len(fc_feats3) > 0

    def test_kinematics_uses_side_prefix(self, sample_columns):
        """k_R_ features need R_Ankle or R_LatShank."""
        result = filter_features_for_sensors(sample_columns, ["R_Ankle"])
        k_r = [c for c in result if c.startswith("k_R")]
        assert len(k_r) > 0

        result2 = filter_features_for_sensors(sample_columns, ["LowerBack"])
        k_r2 = [c for c in result2 if c.startswith("k_R")]
        assert len(k_r2) == 0

    def test_covariates_always_kept(self, sample_columns):
        """cv_, ext_, n_ columns should survive any sensor set."""
        result = filter_features_for_sensors(sample_columns, ["LowerBack"])
        cv_feats = [c for c in result if c.startswith(("cv_", "ext_", "n_"))]
        assert len(cv_feats) > 0
        assert "cv_age" in result
        assert "ext_height" in result
        assert "n_recordings" in result

    def test_duration_always_kept(self, sample_columns):
        result = filter_features_for_sensors(sample_columns, ["LowerBack"])
        assert "duration_s" in result

    def test_distribution_features_follow_sensor(self, sample_columns):
        """dv_, d_, r_ features should respect source sensor."""
        result = filter_features_for_sensors(sample_columns, ["LowerBack"])
        # dv_LowerBack_... should be present
        assert "dv_LowerBack_Acc_X_var" in result
        # dv_R_Wrist_... should be absent
        assert "dv_R_Wrist_Gyr_Z_iqr" not in result

    def test_empty_sensor_set(self, sample_columns):
        """With no sensors, only covariates and metadata survive."""
        result = filter_features_for_sensors(sample_columns, [])
        # Only cv_, ext_, n_, duration_s should survive
        for c in result:
            assert c.startswith(("cv_", "ext_", "n_")) or c == "duration_s", \
                f"Unexpected column with empty sensor set: {c}"

    def test_more_sensors_means_more_features(self, sample_columns):
        """Monotonic: adding sensors should never reduce available features."""
        r1 = filter_features_for_sensors(sample_columns, ["LowerBack"])
        r2 = filter_features_for_sensors(sample_columns, ["LowerBack", "R_Wrist", "L_Wrist"])
        r3 = filter_features_for_sensors(sample_columns, SENSORS)
        assert len(r1) <= len(r2) <= len(r3)

    def test_dst_excluded_by_default(self, sample_columns):
        result = filter_features_for_sensors(sample_columns, SENSORS)
        dst = [c for c in result if c.startswith("dst_")]
        assert len(dst) == 0

    def test_returns_list(self, sample_columns):
        result = filter_features_for_sensors(sample_columns, SENSORS)
        assert isinstance(result, list)

    def test_no_duplicates_in_output(self, sample_columns):
        result = filter_features_for_sensors(sample_columns, SENSORS)
        assert len(result) == len(set(result))

    def test_unknown_columns_kept(self):
        """Columns that don't match any rule should be kept (fallthrough)."""
        cols = ["mystery_feature", "unknown_col"]
        result = filter_features_for_sensors(cols, ["LowerBack"])
        assert "mystery_feature" in result
        assert "unknown_col" in result


# ── Integration: config + filter ────────────────────────────────────


class TestConfigFilterIntegration:
    @pytest.fixture
    def realistic_columns(self):
        """Simulate a subset of the proven_stack_features.csv columns."""
        cols = []
        for s in SENSORS:
            for stat in ["rms", "std", "iqr", "skew", "kurt"]:
                for ax in ["Acc_X", "Acc_Y", "Acc_Z", "Gyr_X", "Gyr_Y", "Gyr_Z"]:
                    cols.append(f"{s}_{ax}_{stat}")
        # Asymmetry
        for pair in ["Wrist", "Ankle", "DorsalFoot", "LatShank", "MidLatThigh"]:
            cols.extend([f"asy_{pair}_rms", f"asy_{pair}_std"])
        # Events
        cols.extend(["ev_n_walks", "trn_count", "sts_time", "bal_area"])
        # Foot contact
        cols.extend(["fc_cadence", "fc_stride_var"])
        # Covariates
        cols.extend(["cv_age", "cv_sex", "ext_bmi"])
        return cols

    def test_no_lowerback_loses_events(self, realistic_columns):
        result = filter_features_for_sensors(realistic_columns, SENSOR_CONFIGS["no_LowerBack"])
        assert "ev_n_walks" not in result
        assert "trn_count" not in result
        assert "sts_time" not in result
        assert "bal_area" not in result

    def test_wrists_only_has_wrist_features_and_covariates(self, realistic_columns):
        result = filter_features_for_sensors(realistic_columns, SENSOR_CONFIGS["wrists_2"])
        for c in result:
            valid = (
                c.startswith("R_Wrist_") or c.startswith("L_Wrist_") or
                c.startswith("asy_Wrist") or
                c.startswith(("cv_", "ext_", "n_")) or
                c == "duration_s"
            )
            assert valid, f"Unexpected column in wrists_2: {c}"

    def test_feet_ankles_has_foot_contact(self, realistic_columns):
        result = filter_features_for_sensors(realistic_columns, SENSOR_CONFIGS["feet_ankles_4"])
        fc_feats = [c for c in result if c.startswith("fc_")]
        assert len(fc_feats) > 0

    def test_upper_body_no_foot_contact(self, realistic_columns):
        result = filter_features_for_sensors(realistic_columns, SENSOR_CONFIGS["upper_body_4"])
        fc_feats = [c for c in result if c.startswith("fc_")]
        assert len(fc_feats) == 0
