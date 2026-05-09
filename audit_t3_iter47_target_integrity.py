"""Audit the current T3 iter47 valid-range target artifacts.

This is a read-only target/artifact integrity audit. It does not refit T3
models. It verifies that the current T3 audit truth is backed by the expected
valid-range target construction, cohort exclusions, preregistration links, and
saved subject/LOSO prediction rows.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from inductive_lib import full_metrics
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter47_invalid_code_fix import (
    COHORTS,
    SEEDS,
    STAGE2_POLICIES,
    filter_cohort,
)


AUDIT_STAMP = "20260508"
METRIC_TOL = 5e-4
EXPECTED_MINIMAL_EXCLUDED = {"NLS151", "NLS188", "WPD013"}
EXPECTED_COMPLETE_EXCLUDED = {
    "NLS036",
    "NLS143",
    "NLS188",
    "NLS183",
    "WPD013",
    "WPD002",
    "NLS151",
    "WPD017",
    "NLS002",
    "NLS210",
}
EXPECTED_INVALID_VALUES = [
    {"sid": "NLS036", "column": "MDSUPDRS_3-15-R", "value": 9.0},
    {"sid": "NLS036", "column": "MDSUPDRS_3-15-L", "value": 9.0},
]
EXPECTED_CHANGED_ROW = {
    "sid": "NLS036",
    "original_sum33": 46.0,
    "validrange_sum33": 28.0,
    "target_delta_original_minus_validrange": 18.0,
    "original_nonmissing": 33,
    "validrange_nonmissing": 31,
    "invalid_part3_count": 2,
}
EXPECTED_HEADLINES = {
    ("drop_allmissing_validrange", "stage2_current"): {"n": 95, "ccc": 0.3784, "mae": 7.5280},
    ("drop_allmissing_validrange", "stage2_no_cv"): {"n": 95, "ccc": 0.3771, "mae": 7.6798},
    ("complete33_validrange", "stage2_current"): {"n": 88, "ccc": 0.4281, "mae": 7.3131},
    ("complete33_validrange", "stage2_no_cv"): {"n": 88, "ccc": 0.4010, "mae": 7.4838},
}
EXPECTED_LOSO = {
    ("drop_allmissing_validrange", "stage2_current"): {
        "n": 95,
        "NLS_to_WPD_mean_ccc": 0.1937,
        "WPD_to_NLS_mean_ccc": 0.1059,
        "two_way_mean_ccc": 0.1498,
    },
    ("drop_allmissing_validrange", "stage2_no_cv"): {
        "n": 95,
        "NLS_to_WPD_mean_ccc": 0.2124666667,
        "WPD_to_NLS_mean_ccc": 0.1138,
        "two_way_mean_ccc": 0.1631333333,
    },
    ("complete33_validrange", "stage2_current"): {
        "n": 88,
        "NLS_to_WPD_mean_ccc": 0.2325,
        "WPD_to_NLS_mean_ccc": -0.0203333333,
        "two_way_mean_ccc": 0.1060833333,
    },
    ("complete33_validrange", "stage2_no_cv"): {
        "n": 88,
        "NLS_to_WPD_mean_ccc": 0.2360333333,
        "WPD_to_NLS_mean_ccc": -0.0042333333,
        "two_way_mean_ccc": 0.1159,
    },
}


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return [_jsonable(v) for v in value.tolist()]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def _record(
    checks: list[dict[str, Any]],
    name: str,
    passed: bool,
    severity: str,
    detail: str,
    observed: Any = None,
) -> None:
    checks.append(
        {
            "name": name,
            "passed": bool(passed),
            "severity": severity,
            "detail": detail,
            "observed": _jsonable(observed),
        }
    )


def _approx(value: Any, expected: float, tol: float = METRIC_TOL) -> bool:
    try:
        return abs(float(value) - float(expected)) <= tol
    except (TypeError, ValueError):
        return False


def _result_path_from_record(record: dict[str, Any], key: str) -> Path:
    return RESULTS_DIR / Path(str(record[key])).name


def _cell_by(result: dict[str, Any], cohort: str, policy: str) -> dict[str, Any]:
    for cell in result.get("cells", []):
        if cell.get("cohort") == cohort and cell.get("stage2_policy") == policy:
            return cell
    return {}


def _sorted_invalid(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [
            {"sid": str(v["sid"]), "column": str(v["column"]), "value": float(v["value"])}
            for v in values
        ],
        key=lambda row: (row["sid"], row["column"]),
    )


def _target_change_rows_for_data(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for sid, y_old, y_new, delta, n_valid in zip(
        data["sids"],
        data["y_t3_original"],
        data["y_t3"],
        data["target_delta_original_minus_validrange"],
        data["raw_nonmissing"],
    ):
        if abs(float(delta)) > 1e-9:
            rows.append(
                {
                    "sid": str(sid),
                    "old_target": float(y_old),
                    "validrange_target": float(y_new),
                    "delta_old_minus_validrange": float(delta),
                    "valid_subitems": int(n_valid),
                }
            )
    return rows


def _write_markdown(path: Path, audit: dict[str, Any]) -> None:
    hard_failures = [
        c for c in audit["checks"]
        if c["severity"] == "hard" and not c["passed"]
    ]
    warnings = [
        c for c in audit["checks"]
        if c["severity"] == "warning" and not c["passed"]
    ]
    lines = [
        "# T3 iter47 Target Integrity Audit",
        "",
        f"- Date stamp: `{AUDIT_STAMP}`",
        f"- Pass: `{audit['pass']}`",
        f"- Hard failures: `{len(hard_failures)}`",
        f"- Warnings: `{len(warnings)}`",
        f"- Invalid raw subitem values: `{len(audit['target']['invalid_raw_subitem_values'])}`",
        f"- Target-changed rows: `{len(audit['target']['target_changed_rows'])}`",
        "",
        "## Target Construction",
        "",
        f"- Part III raw columns: `{audit['target']['n_part3_columns']}`",
        f"- Minimal valid-range N: `{audit['cohorts']['drop_allmissing_validrange']['n']}`",
        f"- Complete33 valid-range N: `{audit['cohorts']['complete33_validrange']['n']}`",
        f"- Minimal excluded SIDs: `{', '.join(audit['cohorts']['drop_allmissing_validrange']['excluded_sids'])}`",
        f"- Complete33 excluded SIDs: `{', '.join(audit['cohorts']['complete33_validrange']['excluded_sids'])}`",
        "",
        "## LOOCV Cells",
        "",
        "| Cohort | Stage-2 policy | N | CCC | MAE | CSV recompute CCC |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in audit["loocv_cells"]:
        lines.append(
            f"| `{row['cohort']}` | `{row['stage2_policy']}` | {row['n']} | "
            f"`{row['json_metrics']['ccc']}` | `{row['json_metrics']['mae']}` | "
            f"`{row['csv_recomputed_metrics']['ccc']}` |"
        )
    lines.extend(["", "## LOSO Cells", "", "| Cohort | Stage-2 policy | N | NLS->WPD | WPD->NLS | Two-way |", "|---|---|---:|---:|---:|---:|"])
    for row in audit["loso_cells"]:
        lines.append(
            f"| `{row['cohort']}` | `{row['stage2_policy']}` | {row['n']} | "
            f"`{row['NLS_to_WPD_mean_ccc']}` | `{row['WPD_to_NLS_mean_ccc']}` | "
            f"`{row['two_way_mean_ccc']}` |"
        )
    if hard_failures:
        lines.extend(["", "## Hard Failures", ""])
        lines.extend(f"- `{c['name']}`: {c['detail']}" for c in hard_failures)
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- `{c['name']}`: {c['detail']}" for c in warnings)
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            (
                "This audit confirms that the current T3 iter47 number is backed by "
                "the intended valid-range target construction and saved prediction "
                "rows. It is not a new model result and does not improve the T3 "
                "ceiling."
            ),
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def run_audit() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    loocv_path = RESULTS_DIR / "iter47_invalidcode_20260508_194605.json"
    loso_path = RESULTS_DIR / "iter47_invalidcode_loso_20260508_195424.json"
    loocv = _load_json(loocv_path)
    loso = _load_json(loso_path)
    loocv_prereg_path = RESULTS_DIR / Path(str(loocv["preregistration_file"])).name
    loso_prereg_path = RESULTS_DIR / Path(str(loso["preregistration_file"])).name
    loocv_prereg = _load_json(loocv_prereg_path)
    loso_prereg = _load_json(loso_prereg_path)
    rows_path = _result_path_from_record(loocv, "rows_csv")
    subj_path = _result_path_from_record(loocv, "subject_predictions_csv")
    loso_rows_path = _result_path_from_record(loso, "rows_csv")
    rows = pd.read_csv(rows_path)
    subj = pd.read_csv(subj_path)
    loso_rows = pd.read_csv(loso_rows_path)

    for path in [loocv_path, loso_path, loocv_prereg_path, loso_prereg_path, rows_path, subj_path, loso_rows_path]:
        _record(
            checks,
            f"exists_{path.name}",
            path.exists(),
            "hard",
            f"Required iter47 artifact must exist: {path.name}",
            str(path),
        )

    _record(
        checks,
        "loocv_prereg_formula_match",
        loocv.get("formula_sha256") == loocv_prereg.get("formula_sha256"),
        "hard",
        "LOOCV result formula hash must match its preregistration.",
        {"result": loocv.get("formula_sha256"), "prereg": loocv_prereg.get("formula_sha256")},
    )
    _record(
        checks,
        "loso_prereg_formula_match",
        loso.get("formula_sha256") == loso_prereg.get("formula_sha256"),
        "hard",
        "LOSO result formula hash must match its preregistration.",
        {"result": loso.get("formula_sha256"), "prereg": loso_prereg.get("formula_sha256")},
    )
    for label, prereg in [("loocv", loocv_prereg), ("loso", loso_prereg)]:
        _record(
            checks,
            f"{label}_prereg_fixed_battery_fields",
            prereg.get("cohorts") == COHORTS
            and prereg.get("stage2_policies") == STAGE2_POLICIES
            and prereg.get("seeds") == SEEDS
            and "no winner selection" in str(prereg.get("no_selection_rule", "")).lower(),
            "hard",
            f"{label.upper()} preregistration must declare the fixed battery, seeds, and no-selection rule.",
            {
                "cohorts": prereg.get("cohorts"),
                "stage2_policies": prereg.get("stage2_policies"),
                "seeds": prereg.get("seeds"),
                "no_selection_rule": prereg.get("no_selection_rule"),
            },
        )

    loocv_target = loocv.get("target_audit", {})
    loso_target = loso.get("target_audit", {})
    _record(
        checks,
        "target_audit_matches_between_loocv_and_loso",
        loocv_target == loso_target,
        "hard",
        "LOOCV and LOSO iter47 artifacts must carry identical target-audit summaries.",
        {"loocv": loocv_target, "loso": loso_target},
    )
    _record(
        checks,
        "target_has_33_part3_columns",
        loocv_target.get("n_part3_columns") == 33,
        "hard",
        "T3 target audit must identify exactly 33 raw Part III subitem columns.",
        loocv_target.get("n_part3_columns"),
    )
    _record(
        checks,
        "invalid_raw_values_are_expected_nls036_9_codes",
        _sorted_invalid(loocv_target.get("invalid_raw_subitem_values", []))
        == _sorted_invalid(EXPECTED_INVALID_VALUES),
        "hard",
        "Only NLS036 item 3.15 R/L raw 9 codes should be invalid in the current target audit.",
        loocv_target.get("invalid_raw_subitem_values"),
    )
    _record(
        checks,
        "target_changed_row_is_expected_nls036_delta18",
        loocv_target.get("target_changed_rows") == [EXPECTED_CHANGED_ROW],
        "hard",
        "Only NLS036 should change target value, from 46 to 28 after valid-range recode.",
        loocv_target.get("target_changed_rows"),
    )

    cohort_summaries: dict[str, Any] = {}
    loocv_cells = []
    for cohort in COHORTS:
        data = filter_cohort(cohort)
        excluded = set(map(str, data["excluded_sids"]))
        expected_excluded = (
            EXPECTED_MINIMAL_EXCLUDED
            if cohort == "drop_allmissing_validrange"
            else EXPECTED_COMPLETE_EXCLUDED
        )
        cohort_summaries[cohort] = {
            "n": int(len(data["sids"])),
            "excluded_sids": sorted(excluded),
            "target_change_subjects": _target_change_rows_for_data(data),
            "clinical_path": str(data["clinical_path"]),
        }
        _record(
            checks,
            f"{cohort}_excluded_sids_match_expected",
            excluded == expected_excluded,
            "hard",
            f"{cohort} must exclude the expected target-missing or incomplete/invalid subjects.",
            sorted(excluded),
        )
        _record(
            checks,
            f"{cohort}_target_values_finite",
            bool(np.isfinite(data["y_t3"]).all()),
            "hard",
            f"{cohort} valid-range target values must be finite.",
            {"n_finite": int(np.isfinite(data["y_t3"]).sum()), "n_total": int(len(data["y_t3"]))},
        )

        sid_to_idx = {str(sid): idx for idx, sid in enumerate(data["sids"])}
        for policy in STAGE2_POLICIES:
            cell = _cell_by(loocv, cohort, policy)
            expected = EXPECTED_HEADLINES[(cohort, policy)]
            group = subj[(subj["cohort"] == cohort) & (subj["stage2_policy"] == policy)].copy()
            csv_sids = set(group["sid"].astype(str))
            y_from_data = np.array([data["y_t3"][sid_to_idx[str(sid)]] for sid in group["sid"].astype(str)])
            pred = group["y_pred"].to_numpy(dtype=float)
            csv_metrics = full_metrics(y_from_data, pred, label=f"{cohort}_{policy}_csv_recompute")

            _record(
                checks,
                f"{cohort}_{policy}_cell_expected_headline",
                cell.get("n") == expected["n"]
                and _approx(cell.get("new_refit_metrics", {}).get("ccc"), expected["ccc"])
                and _approx(cell.get("new_refit_metrics", {}).get("mae"), expected["mae"], 1e-3),
                "hard",
                f"{cohort}/{policy} JSON metrics must match expected iter47 values.",
                {"json": cell.get("new_refit_metrics"), "expected": expected},
            )
            _record(
                checks,
                f"{cohort}_{policy}_subject_csv_sids_match_cohort",
                len(group) == len(data["sids"]) and csv_sids == set(map(str, data["sids"])),
                "hard",
                f"{cohort}/{policy} subject prediction CSV must contain exactly the cohort SIDs once.",
                {"n_rows": int(len(group)), "n_sids": int(len(csv_sids)), "expected_n": int(len(data["sids"]))},
            )
            _record(
                checks,
                f"{cohort}_{policy}_subject_csv_targets_match_loader",
                bool(np.allclose(group["y_true_validrange"].to_numpy(dtype=float), y_from_data, atol=1e-12)),
                "hard",
                f"{cohort}/{policy} subject CSV valid-range targets must match the live target loader.",
                {
                    "max_abs_diff": float(np.max(np.abs(group["y_true_validrange"].to_numpy(dtype=float) - y_from_data)))
                    if len(group)
                    else None
                },
            )
            _record(
                checks,
                f"{cohort}_{policy}_subject_csv_metrics_match_json",
                _approx(csv_metrics.get("ccc"), cell.get("new_refit_metrics", {}).get("ccc"))
                and _approx(csv_metrics.get("mae"), cell.get("new_refit_metrics", {}).get("mae"), 1e-3),
                "hard",
                f"{cohort}/{policy} metrics recomputed from subject CSV must match JSON metrics.",
                {"csv_recomputed": csv_metrics, "json": cell.get("new_refit_metrics")},
            )
            _record(
                checks,
                f"{cohort}_{policy}_rows_csv_has_expected_seeds",
                set(rows[(rows["cohort"] == cohort) & (rows["stage2_policy"] == policy)]["seed"].astype(int)) == set(SEEDS),
                "hard",
                f"{cohort}/{policy} seed rows CSV must contain exactly the expected seeds.",
                rows[(rows["cohort"] == cohort) & (rows["stage2_policy"] == policy)]["seed"].astype(int).tolist(),
            )
            loocv_cells.append(
                {
                    "cohort": cohort,
                    "stage2_policy": policy,
                    "n": int(cell.get("n")),
                    "json_metrics": cell.get("new_refit_metrics"),
                    "csv_recomputed_metrics": csv_metrics,
                    "excluded_sids": sorted(cell.get("excluded_sids", [])),
                    "target_change_subjects": cell.get("target_change_subjects", []),
                }
            )

    loso_cells = []
    for cohort in COHORTS:
        for policy in STAGE2_POLICIES:
            cell = _cell_by(loso, cohort, policy)
            expected = EXPECTED_LOSO[(cohort, policy)]
            group = loso_rows[(loso_rows["cohort"] == cohort) & (loso_rows["stage2_policy"] == policy)].copy()
            nls_vals = group[group["direction"] == "NLS_to_WPD"]["ccc"].to_numpy(dtype=float)
            wpd_vals = group[group["direction"] == "WPD_to_NLS"]["ccc"].to_numpy(dtype=float)
            nls_mean = float(np.mean(nls_vals))
            wpd_mean = float(np.mean(wpd_vals))
            two_way = float((nls_mean + wpd_mean) / 2.0)
            _record(
                checks,
                f"{cohort}_{policy}_loso_expected_headline",
                cell.get("n") == expected["n"]
                and _approx(cell.get("NLS_to_WPD_mean_ccc"), expected["NLS_to_WPD_mean_ccc"])
                and _approx(cell.get("WPD_to_NLS_mean_ccc"), expected["WPD_to_NLS_mean_ccc"])
                and _approx(cell.get("two_way_mean_ccc"), expected["two_way_mean_ccc"]),
                "hard",
                f"{cohort}/{policy} LOSO JSON metrics must match expected iter47 values.",
                {"json": {k: cell.get(k) for k in ["n", "NLS_to_WPD_mean_ccc", "WPD_to_NLS_mean_ccc", "two_way_mean_ccc"]}, "expected": expected},
            )
            _record(
                checks,
                f"{cohort}_{policy}_loso_rows_recompute_means",
                _approx(nls_mean, cell.get("NLS_to_WPD_mean_ccc"))
                and _approx(wpd_mean, cell.get("WPD_to_NLS_mean_ccc"))
                and _approx(two_way, cell.get("two_way_mean_ccc")),
                "hard",
                f"{cohort}/{policy} LOSO row CSV must recompute direction and two-way means.",
                {"row_means": {"NLS_to_WPD": nls_mean, "WPD_to_NLS": wpd_mean, "two_way": two_way}, "json": cell},
            )
            _record(
                checks,
                f"{cohort}_{policy}_loso_rows_have_expected_seed_directions",
                set(group["seed"].astype(int)) == set(SEEDS)
                and set(group["direction"].astype(str)) == {"NLS_to_WPD", "WPD_to_NLS"}
                and len(group) == len(SEEDS) * 2,
                "hard",
                f"{cohort}/{policy} LOSO rows must contain two directions for each seed.",
                {
                    "seeds": sorted(set(group["seed"].astype(int))),
                    "directions": sorted(set(group["direction"].astype(str))),
                    "n_rows": int(len(group)),
                },
            )
            loso_cells.append(
                {
                    "cohort": cohort,
                    "stage2_policy": policy,
                    "n": int(cell.get("n")),
                    "NLS_to_WPD_mean_ccc": nls_mean,
                    "WPD_to_NLS_mean_ccc": wpd_mean,
                    "two_way_mean_ccc": two_way,
                    "excluded_sids": sorted(cell.get("excluded_sids", [])),
                    "target_change_subjects": cell.get("target_change_subjects", []),
                }
            )

    hard_failures = [
        check["name"]
        for check in checks
        if check["severity"] == "hard" and not check["passed"]
    ]
    warnings = [
        check["name"]
        for check in checks
        if check["severity"] == "warning" and not check["passed"]
    ]
    return {
        "audit": "t3_iter47_target_integrity",
        "created_at_utc": "2026-05-08",
        "pass": len(hard_failures) == 0,
        "hard_failures": hard_failures,
        "warnings": warnings,
        "source_artifacts": {
            "loocv_json": loocv_path.name,
            "loocv_preregistration": loocv_prereg_path.name,
            "rows_csv": rows_path.name,
            "subject_predictions_csv": subj_path.name,
            "loso_json": loso_path.name,
            "loso_preregistration": loso_prereg_path.name,
            "loso_rows_csv": loso_rows_path.name,
        },
        "target": {
            "n_part3_columns": loocv_target.get("n_part3_columns"),
            "invalid_raw_subitem_values": loocv_target.get("invalid_raw_subitem_values"),
            "target_changed_rows": loocv_target.get("target_changed_rows"),
        },
        "cohorts": cohort_summaries,
        "loocv_cells": _jsonable(loocv_cells),
        "loso_cells": _jsonable(loso_cells),
        "checks": checks,
        "interpretation": (
            "PASS means the iter47 corrected T3 headline and LOSO rows are "
            "consistent with the valid-range target loader and saved prediction "
            "artifacts. This is target/artifact hardening only, not a new model "
            "result."
        ),
    }


def main() -> None:
    ensure_dir(RESULTS_DIR)
    audit = run_audit()
    json_path = RESULTS_DIR / f"t3_iter47_target_integrity_audit_{AUDIT_STAMP}.json"
    md_path = RESULTS_DIR / f"t3_iter47_target_integrity_audit_{AUDIT_STAMP}.md"
    json_path.write_text(json.dumps(_jsonable(audit), indent=2) + "\n", encoding="utf-8")
    _write_markdown(md_path, audit)
    status = "PASS" if audit["pass"] else "FAIL"
    current = next(
        cell
        for cell in audit["loocv_cells"]
        if cell["cohort"] == "drop_allmissing_validrange" and cell["stage2_policy"] == "stage2_current"
    )
    loso_current = next(
        cell
        for cell in audit["loso_cells"]
        if cell["cohort"] == "drop_allmissing_validrange" and cell["stage2_policy"] == "stage2_current"
    )
    print(f"{status}: wrote {json_path} and {md_path}")
    print(
        "T3 iter47 current recomputed from subject CSV: "
        f"CCC={current['csv_recomputed_metrics']['ccc']:.4f}, "
        f"MAE={current['csv_recomputed_metrics']['mae']:.4f}, "
        f"N={current['n']}"
    )
    print(f"T3 iter47 LOSO two-way from rows: {loso_current['two_way_mean_ccc']:.4f}")
    print(f"Hard failures: {len(audit['hard_failures'])}; warnings: {len(audit['warnings'])}")


if __name__ == "__main__":
    main()
