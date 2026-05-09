"""Audit `dst_*` walkway-distillation features in the V2 cache.

`ablation_v3_features.csv` contains `dst_*` columns produced by
`run_ablation_v2.distill_walkway()`: an XGBoost model is trained once on the
historical dev split to predict pressure-walkway metrics, then predictions are
written for all subjects. Later LOOCV pipelines reuse that frozen cache.

That is not fold-local for LOOCV. This audit asks two narrow questions:
1. Are `dst_*` columns included by the current V2 feature filters?
2. How does the current valid-range T3 iter47 architecture behave when those
   columns are removed from Stage 2?

It is a methodology audit, not a winner-selection experiment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import LeaveOneOut

from eval_utils import lins_ccc as ccc_fn
from inductive_lib import full_metrics
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter2 import feature_select_fold, impute_fold, train_lgb
from run_t3_iter41_target_fix import paired_boot_delta
from run_t3_iter47_invalid_code_fix import SEEDS, filter_cohort
from run_t3_iter5_clinical import FEATURE_SETS, build_stage1_features, fit_stage1, load_clinical_dict


ensure_dir(RESULTS_DIR)

OUT_JSON = RESULTS_DIR / "dst_walkway_leakage_audit_20260508.json"
OUT_MD = RESULTS_DIR / "dst_walkway_leakage_audit_20260508.md"
ROWS_CSV = RESULTS_DIR / "dst_walkway_leakage_audit_rows_20260508.csv"
V2_FEATURES = RESULTS_DIR / "ablation_v3_features.csv"
DEFAULT_POLICIES = ["stage2_current", "stage2_no_dst", "stage2_no_cv", "stage2_no_cv_no_dst"]


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:
        return "unknown"


def _formula_sha(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return [_jsonable(v) for v in value.tolist()]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    return value


def v2_schema_audit() -> dict[str, Any]:
    df = pd.read_csv(V2_FEATURES, nrows=5)
    all_cols = list(df.columns)
    excluded = {"sid", "updrs3", "obs_subscore", "hy"}
    excluded_prefixes = ("nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_")
    selected = [
        col
        for col in all_cols
        if col not in excluded and not any(str(col).startswith(p) for p in excluded_prefixes)
    ]
    prefix_counts = {
        prefix: len([col for col in all_cols if str(col).startswith(prefix)])
        for prefix in ["dst_", "cv_", "nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_"]
    }
    return {
        "v2_path": str(V2_FEATURES),
        "n_columns_total": len(all_cols),
        "n_v2_selected_by_current_filters": len(selected),
        "prefix_counts_total": prefix_counts,
        "dst_columns_total": [col for col in all_cols if str(col).startswith("dst_")],
        "dst_columns_selected_by_current_filters": [
            col for col in selected if str(col).startswith("dst_")
        ],
        "cv_columns_selected_by_current_filters": [
            col for col in selected if str(col).startswith("cv_")
        ],
        "distillation_source": "run_ablation_v3.py build_v3_features() calls run_ablation_v2.distill_walkway(df, wk, dev_sids)",
        "distillation_leakage_risk": (
            "distill_walkway trains XGBRegressor on historical dev_sids once and "
            "writes predictions for all subjects; later LOOCV folds do not refit "
            "that distiller inside the fold."
        ),
    }


def filter_stage2_policy(X: np.ndarray, feat_cols: list[str], policy: str) -> tuple[np.ndarray, list[str]]:
    keep = []
    for i, name in enumerate(feat_cols):
        s = str(name)
        if "no_dst" in policy and s.startswith("dst_"):
            continue
        if "no_cv" in policy and s.startswith("cv_"):
            continue
        keep.append(i)
    return X[:, keep], [feat_cols[i] for i in keep]


def build_stage1_matrix(sids: np.ndarray, hy: np.ndarray) -> np.ndarray:
    clinical = load_clinical_dict(sids)
    X_s1, _names = build_stage1_features(hy, clinical, FEATURE_SETS["A3_tier1"])
    return X_s1


def loocv_preds_for_policy(data: dict[str, Any], policy: str, seed: int) -> tuple[np.ndarray, dict[str, Any]]:
    sids = data["sids"]
    y = data["y_t3"]
    X_s1 = build_stage1_matrix(sids, data["hy"])
    X_s2, feat_cols = filter_stage2_policy(data["X"], data["feat_cols"], policy)
    preds = np.zeros(len(sids), dtype=np.float64)
    selected_prefix_counts = {"dst_": 0, "cv_": 0}
    selected_feature_counts: dict[str, int] = {}
    t0 = time.time()
    for fold_idx, (tr, te) in enumerate(LeaveOneOut().split(np.arange(len(sids)))):
        s1_tr, s1_te = fit_stage1(X_s1[tr], y[tr], X_s1[te], alpha=1.0)
        residual_tr = y[tr] - s1_tr
        Xtr, Xte = impute_fold(X_s2[tr], X_s2[te])
        Xtr_sel, Xte_sel, idx = feature_select_fold(Xtr, residual_tr, Xte, k=500, seed=seed)
        for j in idx:
            name = str(feat_cols[int(j)])
            selected_feature_counts[name] = selected_feature_counts.get(name, 0) + 1
            for prefix in selected_prefix_counts:
                if name.startswith(prefix):
                    selected_prefix_counts[prefix] += 1
        preds[te] = s1_te + train_lgb(Xtr_sel, residual_tr, Xte_sel, seed)
        if (fold_idx + 1) % 25 == 0:
            print(
                f"    {policy} seed={seed}: fold {fold_idx+1}/{len(sids)} "
                f"elapsed={time.time()-t0:.1f}s",
                flush=True,
            )
    top_selected = sorted(
        selected_feature_counts.items(), key=lambda kv: (-kv[1], kv[0])
    )[:30]
    return preds, {
        "n_stage2_features": int(X_s2.shape[1]),
        "selected_prefix_counts": selected_prefix_counts,
        "top_selected_features": top_selected,
    }


def run_audit(policies: list[str], seeds: list[int], tag: str) -> dict[str, Any]:
    out_json = RESULTS_DIR / f"dst_walkway_leakage_audit_{tag}.json"
    out_md = RESULTS_DIR / f"dst_walkway_leakage_audit_{tag}.md"
    rows_csv = RESULTS_DIR / f"dst_walkway_leakage_audit_rows_{tag}.csv"
    subj_path = RESULTS_DIR / f"dst_walkway_leakage_audit_subject_rows_{tag}.csv"
    declaration = {
        "experiment": "dst walkway-distillation leakage audit",
        "trigger": "runtime/provenance audit found ablation_v3_features.csv is the live missing-manifest cache; schema inspection found dst_* columns are included by V2 filters",
        "cohort": "iter47 drop_allmissing_validrange N=95",
        "target": "valid-range corrected MDS-UPDRS Part III",
        "stage1": "iter5 A3_tier1 = H&Y + cv_yrs + cv_sex + cv_dbs",
        "stage2_policies": policies,
        "seeds": list(seeds),
        "evaluation": "LOOCV, mean of seed predictions; no winner selection",
        "interpretation_rule": "If no-dst changes metrics materially, report as leakage/provenance sensitivity, not as a tuned model family.",
    }
    schema = v2_schema_audit()
    data = filter_cohort("drop_allmissing_validrange")

    result_rows = []
    per_subject_rows = []
    policy_results: dict[str, dict[str, Any]] = {}
    policy_mean_preds: dict[str, np.ndarray] = {}
    for policy in policies:
        print(f"\n=== policy={policy} n={len(data['sids'])} ===", flush=True)
        seed_preds = []
        seed_details = {}
        for seed in seeds:
            t0 = time.time()
            preds, detail = loocv_preds_for_policy(data, policy, seed)
            seed_preds.append(preds)
            metrics = full_metrics(data["y_t3"], preds, label=f"{policy}_seed{seed}")
            seed_details[str(seed)] = {
                "metrics": metrics,
                **detail,
                "wall_s": round(time.time() - t0, 1),
            }
            result_rows.append(
                {
                    "policy": policy,
                    "seed": seed,
                    "n": len(data["sids"]),
                    "ccc": float(metrics["ccc"]),
                    "mae": float(metrics["mae"]),
                    "r": float(metrics["r"]),
                    "cal_slope": float(metrics["cal_slope"]),
                    "n_stage2_features": detail["n_stage2_features"],
                    "selected_dst_count": detail["selected_prefix_counts"]["dst_"],
                    "selected_cv_count": detail["selected_prefix_counts"]["cv_"],
                    "wall_s": seed_details[str(seed)]["wall_s"],
                }
            )
            print(
                f"  seed={seed} CCC={metrics['ccc']:+.4f} MAE={metrics['mae']:.3f} "
                f"selected_dst={detail['selected_prefix_counts']['dst_']}",
                flush=True,
            )
        mean_pred = np.mean(np.column_stack(seed_preds), axis=1)
        policy_mean_preds[policy] = mean_pred
        mean_metrics = full_metrics(data["y_t3"], mean_pred, label=f"{policy}_mean")
        policy_results[policy] = {
            "mean_metrics": mean_metrics,
            "seed_details": seed_details,
        }
        for sid, y, pred in zip(data["sids"], data["y_t3"], mean_pred):
            per_subject_rows.append({"policy": policy, "sid": str(sid), "y_true": float(y), "y_pred": float(pred)})
        print(
            f"  ==> {policy} mean CCC={mean_metrics['ccc']:+.4f} MAE={mean_metrics['mae']:.3f}",
            flush=True,
        )

    comparisons = {}
    current_pred = policy_mean_preds["stage2_current"]
    for policy in policies:
        if policy == "stage2_current":
            continue
        comparisons[f"{policy}_minus_current"] = paired_boot_delta(
            data["y_t3"], policy_mean_preds[policy], current_pred
        )

    rows = pd.DataFrame(result_rows)
    subj = pd.DataFrame(per_subject_rows)
    rows.to_csv(rows_csv, index=False)
    subj.to_csv(subj_path, index=False)

    out = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_dst_walkway_leakage.py",
        "git_sha": _git_sha(),
        "declaration": {
            **declaration,
            "formula_sha256": _formula_sha(declaration),
        },
        "schema_audit": schema,
        "cohort": {
            "n": int(len(data["sids"])),
            "excluded_sids": list(map(str, data["excluded_sids"])),
            "target_changed_sids": [
                str(sid)
                for sid, delta in zip(data["sids"], data["target_delta_original_minus_validrange"])
                if abs(float(delta)) > 1e-9
            ],
        },
        "policy_results": policy_results,
        "comparisons": comparisons,
        "rows_csv": str(rows_csv),
        "subject_rows_csv": str(subj_path),
        "verdict": (
            "dst_* columns are included by current V2 filters and were generated by "
            "a once-trained historical dev-split walkway distiller, so they are not "
            "fold-local for LOOCV. The no-dst rows are the leakage/provenance "
            "sensitivity for corrected T3; use the measured deltas, not this audit, "
            "as a new tuned model claim."
        ),
    }
    out_json.write_text(json.dumps(_jsonable(out), indent=2) + "\n", encoding="utf-8")

    lines = [
        "# DST Walkway-Distillation Leakage Audit — 2026-05-08",
        "",
        "`ablation_v3_features.csv` includes `dst_*` columns generated by a once-trained historical dev-split walkway distiller. Current V2 filters include these columns, so this audit measures the corrected T3 sensitivity with those columns removed.",
        "",
        "## Schema",
        "",
        f"- Total columns: `{schema['n_columns_total']}`",
        f"- V2-selected columns under current filters: `{schema['n_v2_selected_by_current_filters']}`",
        f"- `dst_*` total / selected: `{len(schema['dst_columns_total'])}` / `{len(schema['dst_columns_selected_by_current_filters'])}`",
        f"- `cv_*` selected: `{len(schema['cv_columns_selected_by_current_filters'])}`",
        "",
        "## LOOCV Results",
        "",
        "| Policy | CCC | MAE | n stage2 features | selected dst count (seed sum) |",
        "|---|---:|---:|---:|---:|",
    ]
    for policy in policies:
        metrics = policy_results[policy]["mean_metrics"]
        first_seed = next(iter(policy_results[policy]["seed_details"].values()))
        selected_dst = sum(
            detail["selected_prefix_counts"]["dst_"]
            for detail in policy_results[policy]["seed_details"].values()
        )
        lines.append(
            f"| `{policy}` | {float(metrics['ccc']):+.4f} | {float(metrics['mae']):.3f} | "
            f"{first_seed['n_stage2_features']} | {selected_dst} |"
        )
    lines.extend(["", "## Comparisons vs Current", ""])
    for name, comp in comparisons.items():
        lines.append(
            f"- `{name}`: mean delta `{comp['mean_delta']:+.4f}`, "
            f"95% CI `[{comp['ci95'][0]:+.4f}, {comp['ci95'][1]:+.4f}]`, "
            f"frac>0 `{comp['frac_gt_0']:.3f}`"
        )
    lines.extend(["", "## Verdict", "", out["verdict"], "", f"Machine-readable report: `{out_json.relative_to(RESULTS_DIR.parent)}`", ""])
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {out_json}")
    print(f"Wrote {out_md}")
    print(f"Wrote {rows_csv}")
    print(f"Wrote {subj_path}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policies", nargs="+", default=DEFAULT_POLICIES, choices=DEFAULT_POLICIES)
    parser.add_argument("--seeds", nargs="+", type=int, default=list(SEEDS))
    parser.add_argument("--tag", default="20260508")
    args = parser.parse_args()
    run_audit(args.policies, args.seeds, args.tag)


if __name__ == "__main__":
    main()
