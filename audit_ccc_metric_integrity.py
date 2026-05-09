#!/usr/bin/env python3
"""Audit Lin CCC formula and headline metric convention integrity.

This is intentionally not a model run. It checks that the current headline
prediction artifacts are scored with the same population-moment Lin CCC formula
used by the shared metric helpers, and records how much the common sample-moment
variant would move the reported numbers.
"""

from __future__ import annotations

import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from eval_utils import lins_ccc as eval_utils_ccc
from inductive_lib import ccc as inductive_ccc
from inductive_lib import full_metrics


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "ccc_metric_integrity_audit_20260509.json"
OUT_MD = RESULTS / "ccc_metric_integrity_audit_20260509.md"

FORMULA_TOL = 1e-12
CLAIM_TOL = 5e-4


def git_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def finite_pair(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    yt = np.asarray(y_true, dtype=np.float64)
    yp = np.asarray(y_pred, dtype=np.float64)
    mask = np.isfinite(yt) & np.isfinite(yp)
    return yt[mask], yp[mask]


def ccc_population_reference(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Lin CCC with population moments, i.e. 1/N variance/covariance."""
    yt, yp = finite_pair(y_true, y_pred)
    if yt.size < 2 or np.std(yt) < 1e-12 or np.std(yp) < 1e-12:
        return 0.0
    mt = float(np.mean(yt))
    mp = float(np.mean(yp))
    cov = float(np.mean((yt - mt) * (yp - mp)))
    denom = float(np.var(yt) + np.var(yp) + (mt - mp) ** 2)
    return float(2.0 * cov / denom) if denom > 1e-12 else 0.0


def ccc_sample_convention(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Lin CCC variant using sample variance/covariance, kept for sensitivity."""
    yt, yp = finite_pair(y_true, y_pred)
    if yt.size < 3 or np.std(yt, ddof=1) < 1e-12 or np.std(yp, ddof=1) < 1e-12:
        return 0.0
    mt = float(np.mean(yt))
    mp = float(np.mean(yp))
    cov = float(np.sum((yt - mt) * (yp - mp)) / (yt.size - 1))
    denom = float(np.var(yt, ddof=1) + np.var(yp, ddof=1) + (mt - mp) ** 2)
    return float(2.0 * cov / denom) if denom > 1e-12 else 0.0


def safe_metric(fn: Callable[[np.ndarray, np.ndarray], float], y_true: np.ndarray, y_pred: np.ndarray) -> float | str:
    try:
        value = float(fn(y_true, y_pred))
    except Exception as exc:
        return f"ERROR:{type(exc).__name__}:{exc}"
    if math.isnan(value):
        return "nan"
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return value


def round_or_none(value: float | str | None, ndigits: int = 12) -> float | str | None:
    if isinstance(value, float):
        return round(value, ndigits)
    return value


def approx(a: Any, b: Any, tol: float) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def per_subject_json_vector(path: str, name: str, claim_scope: str) -> dict[str, Any]:
    data = load_json(ROOT / path)
    ps = data["per_subject"]
    return {
        "id": name,
        "path": path,
        "claim_scope": claim_scope,
        "sids": list(map(str, ps["sids"])),
        "y_true": np.asarray(ps["y_true"], dtype=float),
        "y_pred": np.asarray(ps["y_pred"], dtype=float),
        "claimed": {key: data.get(key) for key in ("n", "ccc", "mae", "r", "cal_slope")},
    }


def t3_subject_csv_vector(cohort: str, stage2_policy: str, name: str, claim_scope: str) -> dict[str, Any]:
    path = "results/iter47_invalidcode_subject_preds_20260508_194605.csv"
    data = load_json(RESULTS / "iter47_invalidcode_20260508_194605.json")
    df = pd.read_csv(ROOT / path)
    sub = df[(df["cohort"] == cohort) & (df["stage2_policy"] == stage2_policy)].copy()
    claimed = None
    for cell in data["cells"]:
        if cell["cohort"] == cohort and cell["stage2_policy"] == stage2_policy:
            claimed = cell["new_refit_metrics"]
            break
    if claimed is None:
        raise KeyError((cohort, stage2_policy))
    return {
        "id": name,
        "path": path,
        "claim_scope": claim_scope,
        "cohort": cohort,
        "stage2_policy": stage2_policy,
        "sids": sub["sid"].astype(str).tolist(),
        "y_true": sub["y_true_validrange"].to_numpy(float),
        "y_pred": sub["y_pred"].to_numpy(float),
        "claimed": claimed,
    }


def implementation_checks() -> list[dict[str, Any]]:
    vectors = [
        ("identity", np.array([0.0, 1.0, 2.0, 3.0]), np.array([0.0, 1.0, 2.0, 3.0]), True),
        ("shifted", np.array([0.0, 1.0, 2.0, 3.0]), np.array([1.0, 2.0, 3.0, 4.0]), True),
        ("scaled", np.array([0.0, 1.0, 2.0, 3.0]), np.array([0.0, 2.0, 4.0, 6.0]), True),
        ("anti_correlated", np.array([0.0, 1.0, 2.0, 3.0]), np.array([3.0, 2.0, 1.0, 0.0]), True),
        ("constant_prediction", np.array([0.0, 1.0, 2.0, 3.0]), np.array([2.0, 2.0, 2.0, 2.0]), True),
        ("n2_nonconstant", np.array([0.0, 2.0]), np.array([0.0, 1.5]), False),
        ("nan_inf_masked", np.array([0.0, 1.0, np.nan, 3.0, np.inf]), np.array([0.0, 1.2, 2.0, 2.8, 4.0]), False),
    ]
    out: list[dict[str, Any]] = []
    for name, y_true, y_pred, require_exact_match in vectors:
        values = {
            "population_reference": safe_metric(ccc_population_reference, y_true, y_pred),
            "sample_convention": safe_metric(ccc_sample_convention, y_true, y_pred),
            "inductive_lib.ccc": safe_metric(inductive_ccc, y_true, y_pred),
            "eval_utils.lins_ccc": safe_metric(eval_utils_ccc, y_true, y_pred),
        }
        numeric = [
            float(values[key])
            for key in ("population_reference", "inductive_lib.ccc", "eval_utils.lins_ccc")
            if isinstance(values[key], float)
        ]
        max_abs_diff = max([abs(v - numeric[0]) for v in numeric], default=0.0) if numeric else None
        exact_passed = max_abs_diff is not None and max_abs_diff <= FORMULA_TOL
        out.append(
            {
                "id": name,
                "requires_exact_current_impl_match": require_exact_match,
                "values": {key: round_or_none(val) for key, val in values.items()},
                "max_abs_diff_current_impls_vs_reference": max_abs_diff,
                "passed": (not require_exact_match) or exact_passed,
                "note": (
                    "Non-finite/degenerate edge case is recorded as divergence rather than a hard failure."
                    if not require_exact_match
                    else "Finite non-degenerate formula check."
                ),
            }
        )
    return out


def headline_vectors() -> list[dict[str, Any]]:
    return [
        per_subject_json_vector(
            "results/t1_iter12_honest_composite.json",
            "t1_iter12_honest_floor",
            "canonical T1 floor",
        ),
        per_subject_json_vector(
            "results/lockbox_t1_iter34_hybrid_20260506_141720.json",
            "t1_iter34_hybrid_candidate",
            "strongest caveated T1 candidate, not canonical replacement",
        ),
        per_subject_json_vector(
            "results/lockbox_t1_iter46_etrobust_20260508_162825.json",
            "t1_iter46_etrobust_diagnostic",
            "diagnostic negative stop branch",
        ),
        t3_subject_csv_vector(
            "drop_allmissing_validrange",
            "stage2_current",
            "t3_iter47_validrange_current",
            "current corrected valid-range T3 internal headline",
        ),
        t3_subject_csv_vector(
            "drop_allmissing_validrange",
            "stage2_no_cv",
            "t3_iter47_validrange_no_cv_sensitivity",
            "corrected T3 no-cv sensitivity",
        ),
        t3_subject_csv_vector(
            "complete33_validrange",
            "stage2_current",
            "t3_iter47_complete33_current_sensitivity",
            "corrected T3 complete33 sensitivity, not headline",
        ),
        per_subject_json_vector(
            "results/lockbox_t3_iter5_A3_tier1_20260502_171604.json",
            "t3_iter5_historical_target_contaminated",
            "historical target-contaminated artifact only",
        ),
    ]


def check_headline_vector(vec: dict[str, Any]) -> dict[str, Any]:
    y_true = vec["y_true"]
    y_pred = vec["y_pred"]
    sids = vec["sids"]
    pop = ccc_population_reference(y_true, y_pred)
    sample = ccc_sample_convention(y_true, y_pred)
    ind = safe_metric(inductive_ccc, y_true, y_pred)
    ev = safe_metric(eval_utils_ccc, y_true, y_pred)
    fm = full_metrics(y_true, y_pred, label=vec["id"])
    claimed = vec["claimed"]
    finite_mask = np.isfinite(y_true) & np.isfinite(y_pred)
    formula_passed = isinstance(ind, float) and isinstance(ev, float) and abs(pop - ind) <= FORMULA_TOL and abs(pop - ev) <= FORMULA_TOL
    claim_passed = approx(fm.get("ccc"), claimed.get("ccc"), CLAIM_TOL)
    n_passed = int(finite_mask.sum()) == len(y_true) == len(y_pred) == len(sids) == int(claimed.get("n"))
    unique_passed = len(set(sids)) == len(sids)
    sample_delta = sample - pop
    return {
        "id": vec["id"],
        "path": vec["path"],
        "claim_scope": vec["claim_scope"],
        **{k: vec[k] for k in ("cohort", "stage2_policy") if k in vec},
        "n": int(len(sids)),
        "unique_sids": int(len(set(sids))),
        "finite_pairs": int(finite_mask.sum()),
        "claimed_ccc": claimed.get("ccc"),
        "full_metrics_ccc": fm.get("ccc"),
        "population_reference_ccc_unrounded": pop,
        "inductive_lib_ccc_unrounded": ind,
        "eval_utils_ccc_unrounded": ev,
        "sample_convention_ccc_unrounded": sample,
        "sample_minus_population": sample_delta,
        "sample_minus_population_abs": abs(sample_delta),
        "sample_convention_rounded4": round(sample, 4),
        "population_rounded4": round(pop, 4),
        "sample_changes_rounded4": round(sample, 4) != round(pop, 4),
        "formula_passed": formula_passed,
        "claim_passed": claim_passed,
        "n_passed": n_passed,
        "unique_sids_passed": unique_passed,
        "passed": formula_passed and claim_passed and n_passed and unique_passed,
    }


def build_report() -> dict[str, Any]:
    impl = implementation_checks()
    headline = [check_headline_vector(vec) for vec in headline_vectors()]
    hard_failures = []
    warnings = []
    for check in impl:
        if not check["passed"]:
            hard_failures.append(f"implementation:{check['id']}")
        ind_value = check["values"].get("inductive_lib.ccc")
        eval_value = check["values"].get("eval_utils.lins_ccc")
        ref_value = check["values"].get("population_reference")
        if ind_value != eval_value:
            warnings.append(
                {
                    "id": f"helper_edge_case_divergence:{check['id']}",
                    "message": "Shared metric helpers differ on an edge-case vector; headline vectors are finite and non-degenerate.",
                    "values": check["values"],
                }
            )
        elif check["id"] == "n2_nonconstant" and ind_value != ref_value:
            warnings.append(
                {
                    "id": "degenerate_n2_policy_returns_zero",
                    "message": "Shared helpers intentionally return 0.0 for fewer than three finite pairs; headline vectors are unaffected.",
                    "values": check["values"],
                }
            )
    for check in headline:
        if not check["passed"]:
            hard_failures.append(f"headline:{check['id']}")
        if check["sample_changes_rounded4"]:
            warnings.append(
                {
                    "id": f"sample_convention_changes_rounded4:{check['id']}",
                    "message": "A sample-moment CCC convention would change the fourth decimal; current policy remains Lin population-moment CCC.",
                    "sample_minus_population": check["sample_minus_population"],
                }
            )
    max_sample_abs = max(abs(check["sample_minus_population"]) for check in headline)
    return {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_ccc_metric_integrity.py",
        "git_sha": git_sha(),
        "policy": (
            "Reportable CCC uses Lin's population-moment concordance formula: "
            "2*cov_pop(y,p)/(var_pop(y)+var_pop(p)+(mean(y)-mean(p))^2). "
            "Sample-moment CCC is recorded only as a convention sensitivity."
        ),
        "external_formula_sources": [
            {
                "name": "Lin CCC formula overview",
                "url": "https://www.medcalc.org/en/manual/concordance.php",
            },
            {
                "name": "Population-vs-sample convention note",
                "url": "https://en.wikipedia.org/wiki/Concordance_correlation_coefficient",
            },
        ],
        "formula_tolerance": FORMULA_TOL,
        "claim_tolerance": CLAIM_TOL,
        "passed": not hard_failures,
        "hard_failures": hard_failures,
        "warnings": warnings,
        "max_abs_sample_minus_population_headline": max_sample_abs,
        "implementation_checks": impl,
        "headline_checks": headline,
    }


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# CCC Metric Integrity Audit - 2026-05-09",
        "",
        report["policy"],
        "",
        f"- Passed: `{report['passed']}`",
        f"- Hard failures: `{len(report['hard_failures'])}`",
        f"- Warnings: `{len(report['warnings'])}`",
        f"- Max absolute sample-minus-population shift on headline vectors: `{report['max_abs_sample_minus_population_headline']:.8f}`",
        "",
        "## Headline Vectors",
        "",
        "| ID | Scope | N | Claimed CCC | Population CCC | Sample CCC | Sample - Population | Passed |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for check in report["headline_checks"]:
        lines.append(
            "| {id} | {scope} | {n} | {claimed:.4f} | {pop:.8f} | {sample:.8f} | {delta:+.8f} | `{passed}` |".format(
                id=check["id"],
                scope=check["claim_scope"],
                n=check["n"],
                claimed=float(check["claimed_ccc"]),
                pop=float(check["population_reference_ccc_unrounded"]),
                sample=float(check["sample_convention_ccc_unrounded"]),
                delta=float(check["sample_minus_population"]),
                passed=check["passed"],
            )
        )
    lines.extend(["", "## Implementation Checks", ""])
    for check in report["implementation_checks"]:
        lines.append(f"### {check['id']}")
        lines.append("")
        lines.append(f"- Passed: `{check['passed']}`")
        lines.append(f"- Requires exact current implementation match: `{check['requires_exact_current_impl_match']}`")
        lines.append(f"- Max abs diff current implementations vs reference: `{check['max_abs_diff_current_impls_vs_reference']}`")
        for key, value in check["values"].items():
            lines.append(f"- `{key}`: `{value}`")
        lines.append("")
    if report["warnings"]:
        lines.extend(["## Warnings", ""])
        for warning in report["warnings"]:
            lines.append(f"- `{warning['id']}`: {warning['message']}")
    lines.extend(["", f"Machine-readable report: `{OUT_JSON.relative_to(ROOT)}`", ""])
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    report = build_report()
    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_markdown(report)
    print(f"Wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"Wrote {OUT_MD.relative_to(ROOT)}")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "hard_failures": len(report["hard_failures"]),
                "warnings": len(report["warnings"]),
                "headline_checks": len(report["headline_checks"]),
                "implementation_checks": len(report["implementation_checks"]),
            },
            indent=2,
        )
    )
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
