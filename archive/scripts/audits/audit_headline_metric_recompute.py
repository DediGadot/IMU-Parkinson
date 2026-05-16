#!/usr/bin/env python3
"""Recompute current headline metrics from stored prediction artifacts.

The current-state verifier checks many summary JSON fields. This audit checks a
lower layer: do the stored per-subject prediction artifacts recompute to the
claimed CCC/MAE/r/calibration values?
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from inductive_lib import full_metrics


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "headline_metric_recompute_audit_20260508.json"
OUT_MD = RESULTS / "headline_metric_recompute_audit_20260508.md"

TOL = 5e-4


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def approx(a: Any, b: Any, tol: float = TOL) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def compare_metric_dict(recomputed: dict[str, Any], claimed: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    comparisons = []
    passed = True
    for key in keys:
        ok = approx(recomputed.get(key), claimed.get(key))
        comparisons.append(
            {
                "metric": key,
                "recomputed": recomputed.get(key),
                "claimed": claimed.get(key),
                "passed": ok,
            }
        )
        passed = passed and ok
    return {"passed": passed, "comparisons": comparisons}


def recompute_from_per_subject(path: Path, label: str) -> dict[str, Any]:
    data = load_json(path)
    ps = data["per_subject"]
    y_true = np.asarray(ps["y_true"], dtype=float)
    y_pred = np.asarray(ps["y_pred"], dtype=float)
    sids = list(map(str, ps["sids"]))
    recomputed = full_metrics(y_true, y_pred, label=label)
    claimed = {key: data.get(key) for key in ["n", "ccc", "mae", "r", "cal_slope"]}
    return {
        "name": label,
        "source": str(path.relative_to(ROOT)),
        "method": "full_metrics(per_subject.y_true, per_subject.y_pred)",
        "n_sids": len(sids),
        "unique_sids": len(set(sids)),
        "recomputed": recomputed,
        "claimed": claimed,
        **compare_metric_dict(recomputed, claimed, ["n", "ccc", "mae", "r", "cal_slope"]),
    }


def t3_cell(json_path: Path, cohort: str, policy: str) -> dict[str, Any]:
    data = load_json(json_path)
    for cell in data["cells"]:
        if cell["cohort"] == cohort and cell["stage2_policy"] == policy:
            return cell
    raise KeyError((cohort, policy))


def recompute_t3_subject_cell(
    csv_path: Path,
    json_path: Path,
    cohort: str,
    policy: str,
    label: str,
) -> dict[str, Any]:
    df = pd.read_csv(csv_path)
    sub = df[(df["cohort"] == cohort) & (df["stage2_policy"] == policy)].copy()
    recomputed = full_metrics(sub["y_true_validrange"].to_numpy(float), sub["y_pred"].to_numpy(float), label=label)
    claimed = t3_cell(json_path, cohort, policy)["new_refit_metrics"]
    return {
        "name": label,
        "source": str(csv_path.relative_to(ROOT)),
        "summary_source": str(json_path.relative_to(ROOT)),
        "method": "full_metrics(subject_predictions.y_true_validrange, subject_predictions.y_pred)",
        "cohort": cohort,
        "stage2_policy": policy,
        "n_rows": int(len(sub)),
        "unique_sids": int(sub["sid"].astype(str).nunique()),
        "recomputed": recomputed,
        "claimed": claimed,
        **compare_metric_dict(recomputed, claimed, ["n", "ccc", "mae", "r", "cal_slope"]),
    }


def recompute_dst_policy(policy: str) -> dict[str, Any]:
    csv_path = RESULTS / "dst_walkway_leakage_audit_subject_rows_20260508_multiseed.csv"
    json_path = RESULTS / "dst_walkway_leakage_audit_20260508_multiseed.json"
    df = pd.read_csv(csv_path)
    sub = df[df["policy"] == policy].copy()
    label = f"dst_audit_{policy}"
    recomputed = full_metrics(sub["y_true"].to_numpy(float), sub["y_pred"].to_numpy(float), label=label)
    claimed = load_json(json_path)["policy_results"][policy]["mean_metrics"]
    return {
        "name": label,
        "source": str(csv_path.relative_to(ROOT)),
        "summary_source": str(json_path.relative_to(ROOT)),
        "method": "full_metrics(dst_subject_rows.y_true, dst_subject_rows.y_pred)",
        "policy": policy,
        "n_rows": int(len(sub)),
        "unique_sids": int(sub["sid"].astype(str).nunique()),
        "recomputed": recomputed,
        "claimed": claimed,
        **compare_metric_dict(recomputed, claimed, ["n", "ccc", "mae", "r", "cal_slope"]),
    }


def recompute_loso_cell(cohort: str, policy: str) -> dict[str, Any]:
    rows_path = RESULTS / "iter47_invalidcode_loso_rows_20260508_195424.csv"
    json_path = RESULTS / "iter47_invalidcode_loso_20260508_195424.json"
    rows = pd.read_csv(rows_path)
    sub = rows[(rows["cohort"] == cohort) & (rows["stage2_policy"] == policy)].copy()
    by_direction = sub.groupby("direction")["ccc"].mean().to_dict()
    recomputed = {
        "NLS_to_WPD_mean_ccc": round(float(by_direction.get("NLS_to_WPD", np.nan)), 4),
        "WPD_to_NLS_mean_ccc": round(float(by_direction.get("WPD_to_NLS", np.nan)), 4),
    }
    recomputed["two_way_mean_ccc"] = round(
        float(np.mean([recomputed["NLS_to_WPD_mean_ccc"], recomputed["WPD_to_NLS_mean_ccc"]])),
        4,
    )
    claimed_cell = t3_cell(json_path, cohort, policy)
    claimed = {
        "NLS_to_WPD_mean_ccc": claimed_cell.get("NLS_to_WPD_mean_ccc"),
        "WPD_to_NLS_mean_ccc": claimed_cell.get("WPD_to_NLS_mean_ccc"),
        "two_way_mean_ccc": claimed_cell.get("two_way_mean_ccc"),
    }
    return {
        "name": f"t3_iter47_loso_{cohort}_{policy}",
        "source": str(rows_path.relative_to(ROOT)),
        "summary_source": str(json_path.relative_to(ROOT)),
        "method": "mean per-seed CCC by LOSO direction from rows CSV, then two-way mean",
        "cohort": cohort,
        "stage2_policy": policy,
        "n_rows": int(len(sub)),
        "recomputed": recomputed,
        "claimed": claimed,
        **compare_metric_dict(
            recomputed,
            claimed,
            ["NLS_to_WPD_mean_ccc", "WPD_to_NLS_mean_ccc", "two_way_mean_ccc"],
        ),
    }


def build_report() -> dict[str, Any]:
    checks = [
        recompute_from_per_subject(
            RESULTS / "t1_iter12_honest_composite.json",
            "t1_iter12_honest_floor",
        ),
        recompute_from_per_subject(
            RESULTS / "lockbox_t1_iter34_hybrid_20260506_141720.json",
            "t1_iter34_hybrid_candidate",
        ),
        recompute_t3_subject_cell(
            RESULTS / "iter47_invalidcode_subject_preds_20260508_194605.csv",
            RESULTS / "iter47_invalidcode_20260508_194605.json",
            "drop_allmissing_validrange",
            "stage2_current",
            "t3_iter47_validrange_current",
        ),
        recompute_t3_subject_cell(
            RESULTS / "iter47_invalidcode_subject_preds_20260508_194605.csv",
            RESULTS / "iter47_invalidcode_20260508_194605.json",
            "drop_allmissing_validrange",
            "stage2_no_cv",
            "t3_iter47_validrange_no_cv",
        ),
        recompute_t3_subject_cell(
            RESULTS / "iter47_invalidcode_subject_preds_20260508_194605.csv",
            RESULTS / "iter47_invalidcode_20260508_194605.json",
            "complete33_validrange",
            "stage2_current",
            "t3_iter47_complete33_current_sensitivity",
        ),
        recompute_dst_policy("stage2_current"),
        recompute_dst_policy("stage2_no_dst"),
        recompute_loso_cell("drop_allmissing_validrange", "stage2_current"),
        recompute_loso_cell("drop_allmissing_validrange", "stage2_no_cv"),
    ]
    passed = all(check["passed"] for check in checks)
    return {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_headline_metric_recompute.py",
        "policy": "Recompute headline/candidate metrics from stored per-subject prediction artifacts where available; LOSO is recomputed from per-seed rows.",
        "tolerance": TOL,
        "passed": passed,
        "checks": checks,
    }


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# Headline Metric Recompute Audit - 2026-05-08",
        "",
        report["policy"],
        "",
        f"- Passed: `{report['passed']}`",
        f"- Tolerance: `{report['tolerance']}`",
        f"- Checks: `{len(report['checks'])}`",
        "",
        "## Checks",
        "",
    ]
    for check in report["checks"]:
        lines.append(f"### {check['name']}")
        lines.append("")
        lines.append(f"- Passed: `{check['passed']}`")
        lines.append(f"- Source: `{check['source']}`")
        if "summary_source" in check:
            lines.append(f"- Summary source: `{check['summary_source']}`")
        lines.append(f"- Method: {check['method']}")
        for comp in check["comparisons"]:
            lines.append(
                f"- `{comp['metric']}` recomputed `{comp['recomputed']}` vs claimed `{comp['claimed']}` -> `{comp['passed']}`"
            )
        lines.append("")
    lines.extend(["", f"Machine-readable report: `{OUT_JSON.relative_to(ROOT)}`", ""])
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    report = build_report()
    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_markdown(report)
    print(f"Wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"Wrote {OUT_MD.relative_to(ROOT)}")
    print(json.dumps({"passed": report["passed"], "checks": len(report["checks"])}, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
