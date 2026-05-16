"""Fold-firewall facade for new code."""

from inductive_lib import (
    FoldImputer,
    FoldNormalizer,
    FoldSeverityBins,
    assert_library_excludes_test,
    fit_demo_ridge,
    gen_5fold_split,
    null_canary_feature,
    null_scrambled_label,
    null_subject_id_shuffle,
    run_null_test_gate,
    transductive_sanity_predict,
    write_preregistration,
)

__all__ = [
    "FoldImputer",
    "FoldNormalizer",
    "FoldSeverityBins",
    "assert_library_excludes_test",
    "fit_demo_ridge",
    "gen_5fold_split",
    "null_canary_feature",
    "null_scrambled_label",
    "null_subject_id_shuffle",
    "run_null_test_gate",
    "transductive_sanity_predict",
    "write_preregistration",
]

