"""Temporary facade for stable helpers still housed in historical scripts.

New experiment scripts should import this facade instead of importing other
``run_*.py`` files directly. The underlying helpers can later be moved into
proper core modules without changing new callers.
"""

from __future__ import annotations

from run_t1_iter4 import T1_ITEMS
from run_t1_iter33b_8item_chain import ALL_ITEMS, AUX_ITEMS, T1_SUM_ITEMS, _load_t1_cohort_with_8items
from run_t3_iter2 import feature_select_fold, impute_fold, train_lgb
from run_t3_iter5_clinical import FEATURE_SETS as ITER5_FEATURE_SETS
from run_t3_iter5_clinical import build_stage1_features, fit_stage1, load_clinical_dict

__all__ = [
    "ALL_ITEMS",
    "AUX_ITEMS",
    "ITER5_FEATURE_SETS",
    "T1_ITEMS",
    "T1_SUM_ITEMS",
    "_load_t1_cohort_with_8items",
    "build_stage1_features",
    "feature_select_fold",
    "fit_stage1",
    "impute_fold",
    "load_clinical_dict",
    "train_lgb",
]
