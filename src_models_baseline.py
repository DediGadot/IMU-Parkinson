"""
Baseline models for PD classification and UPDRS prediction.
Uses handcrafted gait features with XGBoost / RandomForest.
"""
import numpy as np
from dataclasses import dataclass
from typing import Optional
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import LeaveOneGroupOut, cross_val_predict
from sklearn.metrics import (
    accuracy_score, f1_score, mean_absolute_error,
    classification_report, confusion_matrix,
)
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
import xgboost as xgb


@dataclass(frozen=True)
class BaselineResults:
    """Immutable container for baseline evaluation results."""
    task: str
    model_name: str
    accuracy: Optional[float]
    f1_macro: Optional[float]
    mae: Optional[float]
    predictions: np.ndarray
    true_labels: np.ndarray
    report: str


def build_xgb_classifier(n_classes: int = 2) -> Pipeline:
    """XGBoost classifier pipeline with standard scaling."""
    return Pipeline([
        ("scaler", StandardScaler()),
        ("xgb", xgb.XGBClassifier(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.1,
            subsample=0.8,
            colsample_bytree=0.8,
            use_label_encoder=False,
            eval_metric="mlogloss" if n_classes > 2 else "logloss",
            random_state=42,
        )),
    ])


def build_xgb_regressor() -> Pipeline:
    """XGBoost regressor pipeline for UPDRS prediction."""
    return Pipeline([
        ("scaler", StandardScaler()),
        ("xgb", xgb.XGBRegressor(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.1,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
        )),
    ])


def build_rf_classifier(n_classes: int = 2) -> Pipeline:
    """Random Forest classifier pipeline."""
    return Pipeline([
        ("scaler", StandardScaler()),
        ("rf", RandomForestClassifier(
            n_estimators=200,
            max_depth=10,
            random_state=42,
            n_jobs=-1,
        )),
    ])


def evaluate_pd_vs_control(
    features: np.ndarray,
    labels: np.ndarray,
    groups: np.ndarray,
) -> BaselineResults:
    """PD vs Control classification with leave-one-subject-out CV.

    Args:
        features: (N, 15) gait feature matrix
        labels: (N,) binary labels (0=control, 1=pd)
        groups: (N,) subject IDs for LOSO cross-validation
    """
    logo = LeaveOneGroupOut()
    model = build_xgb_classifier(n_classes=2)

    preds = cross_val_predict(model, features, labels, groups=groups, cv=logo)

    acc = accuracy_score(labels, preds)
    f1 = f1_score(labels, preds, average="macro")
    report = classification_report(labels, preds, target_names=["Control", "PD"])

    return BaselineResults(
        task="pd_vs_control",
        model_name="XGBoost",
        accuracy=acc,
        f1_macro=f1,
        mae=None,
        predictions=preds,
        true_labels=labels,
        report=report,
    )


def evaluate_hy_stage(
    features: np.ndarray,
    labels: np.ndarray,
    groups: np.ndarray,
) -> BaselineResults:
    """H&Y stage classification with LOSO CV.

    Args:
        features: (N, 15) gait feature matrix
        labels: (N,) H&Y stage (1-5)
        groups: (N,) subject IDs
    """
    n_classes = len(np.unique(labels))
    logo = LeaveOneGroupOut()
    model = build_xgb_classifier(n_classes=n_classes)

    preds = cross_val_predict(model, features, labels, groups=groups, cv=logo)

    acc = accuracy_score(labels, preds)
    f1 = f1_score(labels, preds, average="macro")
    mae = mean_absolute_error(labels, preds)
    report = classification_report(labels, preds)

    return BaselineResults(
        task="hy_stage",
        model_name="XGBoost",
        accuracy=acc,
        f1_macro=f1,
        mae=mae,
        predictions=preds,
        true_labels=labels,
        report=report,
    )


def evaluate_updrs_regression(
    features: np.ndarray,
    scores: np.ndarray,
    groups: np.ndarray,
) -> BaselineResults:
    """UPDRS score regression with LOSO CV.

    Args:
        features: (N, 15) gait feature matrix
        scores: (N,) continuous UPDRS scores
        groups: (N,) subject IDs
    """
    logo = LeaveOneGroupOut()
    model = build_xgb_regressor()

    preds = cross_val_predict(model, features, scores, groups=groups, cv=logo)

    mae = mean_absolute_error(scores, preds)

    return BaselineResults(
        task="updrs_regression",
        model_name="XGBoost",
        accuracy=None,
        f1_macro=None,
        mae=mae,
        predictions=preds,
        true_labels=scores,
        report=f"UPDRS MAE: {mae:.2f}",
    )
