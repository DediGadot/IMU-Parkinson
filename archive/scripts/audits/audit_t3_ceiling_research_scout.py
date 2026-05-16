#!/usr/bin/env python3
"""Decision audit for the corrected T3 CCC ceiling.

This is a diagnostic-only research scout. It does not fit a reportable model,
write a preregistration, run LOOCV, or change any canonical claim. The purpose
is to make the current T3 stop rule reproducible: quantify whether the saved T1
OOF predictions plausibly bridge to corrected T3, then rank external data routes
by how well their protocol could observe the Part III domains that WearGait-PD
misses.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from eval_utils import lins_ccc
from project_paths import RESULTS_DIR


ROOT = Path(__file__).resolve().parent
RESULTS = RESULTS_DIR

T3_PRED_PATH = RESULTS / "iter47_invalidcode_subject_preds_20260508_194605.csv"
T1_ITER12_PATH = RESULTS / "t1_iter12_honest_composite.json"
T1_ITER34_PATH = RESULTS / "lockbox_t1_iter34_hybrid_20260506_141720.json"
RESIDUAL_ANATOMY_PATH = RESULTS / "t3_iter47_residual_anatomy_20260509.json"
DOMAIN_RESIDUAL_PATH = RESULTS / "t3_iter47_domain_residual_audit_20260509.json"
ITEM_RESIDUAL_PATH = RESULTS / "t3_iter47_item_residual_audit_20260509.json"
EXTERNAL_ROUTES_PATH = RESULTS / "external_dataset_route_audit_20260508.json"
RECENT_WEB_LEADS_PATH = RESULTS / "recent_external_web_leads_20260509.json"
ACCESS_READINESS_PATH = RESULTS / "external_access_readiness_audit_20260509.json"
BLOCKER_ACTIONS_PATH = RESULTS / "remaining_blocker_action_audit_20260509.json"

OUT_JSON = RESULTS / "t3_ceiling_research_scout_20260509.json"
OUT_MD = RESULTS / "t3_ceiling_research_scout_20260509.md"


REQUIRED_FILES = [
    T3_PRED_PATH,
    T1_ITER12_PATH,
    T1_ITER34_PATH,
    RESIDUAL_ANATOMY_PATH,
    DOMAIN_RESIDUAL_PATH,
    ITEM_RESIDUAL_PATH,
    EXTERNAL_ROUTES_PATH,
    RECENT_WEB_LEADS_PATH,
    ACCESS_READINESS_PATH,
    BLOCKER_ACTIONS_PATH,
]


FRESH_SOURCE_NOTES = [
    {
        "name": "PubMed 2025-2026 wearable/IMU/smartwatch UPDRS query",
        "source": "NCBI ESearch",
        "finding": "Query returned 60 PubMed hits, confirming the active literature has moved toward longitudinal/free-living digital motor endpoints and access-gated cohorts rather than small-N single-session estimator tuning.",
    },
    {
        "name": "PPMI / Verily Study Watch prodromal PD progression paper",
        "source": "https://www.nature.com/articles/s41531-025-01034-8",
        "finding": "Wrist Study Watch data at 100 Hz were linked to MDS-UPDRS Part III within 90 days; PPMI remains the highest-priority gated route for a future schema probe.",
    },
    {
        "name": "ICICLE-GAIT federated learning paper",
        "source": "https://www.frontiersin.org/journals/aging-neuroscience/articles/10.3389/fnagi.2026.1766599/full",
        "finding": "Lower-back AX3 free-living gait with MDS-UPDRS Part III is a real direct T3 route, but it mostly covers gait/axial burden rather than the non-gait residual domains now limiting WearGait T3.",
    },
    {
        "name": "COPS Scientific Data 2026",
        "source": "https://www.nature.com/articles/s41597-026-06999-6",
        "finding": "Public bilateral wrist accelerometry includes UPDRS-III OFF/ON CSVs; already tested as iter49 and remains external-validity evidence only.",
    },
]


KIMI_CONSULT_SUMMARY = {
    "tool": "opencode Kimi CLI",
    "session_id": "ses_1f333adeaffe17sW7gYoKbRZiF",
    "verdict": "useful_as_decision_audit_not_model_discovery",
    "highest_leverage_next_action": "Submit/complete PPMI-Verily access, then run only a read-only schema probe after approval.",
    "absolute_prohibitions": [
        "No WearGait-only T3 model screen from this audit.",
        "No preregistration, LOOCV, lockbox, or canonical update from the T1-to-T3 scaffold.",
        "No true T1, item, domain, or residual labels as production features.",
        "No calibration, variance rescaling, sample weighting, tail weighting, or residual smoothing retry.",
        "No gated-dataset loader scaffold before credentials and row-level schema exist.",
    ],
}


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def require_files() -> None:
    missing = [str(path) for path in REQUIRED_FILES if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing required T3 research-scout inputs: " + ", ".join(missing))


def corr(a: np.ndarray, b: np.ndarray) -> float | None:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    mask = np.isfinite(a) & np.isfinite(b)
    if int(mask.sum()) < 5:
        return None
    aa = a[mask]
    bb = b[mask]
    if np.std(aa) < 1e-12 or np.std(bb) < 1e-12:
        return None
    return float(np.corrcoef(aa, bb)[0, 1])


def metrics(y: np.ndarray, pred: np.ndarray) -> dict[str, Any]:
    y = np.asarray(y, dtype=float)
    pred = np.asarray(pred, dtype=float)
    err = pred - y
    return {
        "n": int(len(y)),
        "ccc": float(lins_ccc(y, pred)),
        "mae": float(np.mean(np.abs(err))),
        "r": corr(y, pred),
        "prediction_sd": float(np.std(pred)),
        "target_sd": float(np.std(y)),
        "residual_corr_with_true": corr(err, y),
    }


def loo_ridge_predict(x: np.ndarray, y: np.ndarray, alpha: float = 1.0) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.ndim == 1:
        x = x.reshape(-1, 1)
    pred = np.full(len(y), np.nan, dtype=float)
    for held_out in range(len(y)):
        train_mask = np.ones(len(y), dtype=bool)
        train_mask[held_out] = False
        x_train = x[train_mask]
        y_train = y[train_mask]
        finite_train = np.isfinite(y_train) & np.all(np.isfinite(x_train), axis=1)
        finite_test = bool(np.all(np.isfinite(x[held_out])))
        if int(finite_train.sum()) < x.shape[1] + 2 or not finite_test:
            pred[held_out] = float(np.nanmean(y_train))
            continue
        xx = x_train[finite_train]
        yy = y_train[finite_train]
        mean = np.mean(xx, axis=0)
        sd = np.std(xx, axis=0)
        sd[sd < 1e-12] = 1.0
        z = (xx - mean) / sd
        design = np.column_stack([np.ones(len(z)), z])
        penalty = np.eye(design.shape[1]) * alpha
        penalty[0, 0] = 0.0
        beta = np.linalg.solve(design.T @ design + penalty, design.T @ yy)
        test_z = (x[held_out] - mean) / sd
        pred[held_out] = float(np.r_[1.0, test_z] @ beta)
    return pred


def t3_current_predictions() -> pd.DataFrame:
    df = pd.read_csv(T3_PRED_PATH)
    df = df[
        (df["cohort"] == "drop_allmissing_validrange")
        & (df["stage2_policy"] == "stage2_current")
    ].copy()
    if df.empty:
        raise ValueError("No iter47 current-stage2 predictions found")
    df["sid"] = df["sid"].astype(str)
    df = df.rename(columns={"y_true_validrange": "t3_true", "y_pred": "t3_pred"})
    return df[["sid", "t3_true", "t3_pred"]]


def t1_table(path: Path, label: str) -> pd.DataFrame:
    data = read_json(path)
    per_subject = data.get("per_subject", {})
    required = ["sids", "y_true", "y_pred"]
    if any(key not in per_subject for key in required):
        raise ValueError(f"{path} lacks per_subject sids/y_true/y_pred")
    return pd.DataFrame(
        {
            "sid": [str(sid) for sid in per_subject["sids"]],
            f"{label}_true": per_subject["y_true"],
            f"{label}_pred": per_subject["y_pred"],
        }
    )


def scaffold_report() -> dict[str, Any]:
    base = t3_current_predictions()
    reports = []
    for label, path in [("t1_iter12", T1_ITER12_PATH), ("t1_iter34", T1_ITER34_PATH)]:
        joined = base.merge(t1_table(path, label), on="sid", how="inner")
        y = joined["t3_true"].to_numpy(float)
        current_pred = joined["t3_pred"].to_numpy(float)
        t1_pred = joined[f"{label}_pred"].to_numpy(float)
        t1_true = joined[f"{label}_true"].to_numpy(float)
        scaffold_pred = loo_ridge_predict(t1_pred, y)
        true_t1_oracle_pred = loo_ridge_predict(t1_true, y)
        reports.append(
            {
                "label": label,
                "input_artifact": str(path.relative_to(ROOT)),
                "n_intersection_with_iter47_t3": int(len(joined)),
                "scope": "diagnostic_oof_level_not_fully_nested_no_model_promotion",
                "current_t3_metrics_on_intersection": metrics(y, current_pred),
                "t1_oof_prediction_to_t3_loo_ridge": metrics(y, scaffold_pred),
                "true_t1_to_t3_privileged_oracle": metrics(y, true_t1_oracle_pred),
                "delta_scaffold_ccc_vs_current_intersection": float(
                    lins_ccc(y, scaffold_pred) - lins_ccc(y, current_pred)
                ),
                "interpretation": interpret_scaffold(y, current_pred, scaffold_pred, true_t1_oracle_pred),
            }
        )
    return {
        "guardrail": "OOF-level scaffold is diagnostic only. Base OOF predictions for meta-training rows may have trained on the held-out meta subject, so this is not a valid lockbox or promotion gate.",
        "reports": reports,
    }


def interpret_scaffold(
    y: np.ndarray, current_pred: np.ndarray, scaffold_pred: np.ndarray, oracle_pred: np.ndarray
) -> list[str]:
    current_ccc = float(lins_ccc(y, current_pred))
    scaffold_ccc = float(lins_ccc(y, scaffold_pred))
    oracle_ccc = float(lins_ccc(y, oracle_pred))
    notes = []
    if scaffold_ccc <= current_ccc + 0.025:
        notes.append("Saved T1 OOF predictions do not provide a detectable corrected-T3 scaffold beyond the current iter47 predictor.")
    else:
        notes.append("Saved T1 OOF predictions contain diagnostic T3 signal, but the OOF-level stack is not fully nested and cannot be promoted.")
    if oracle_ccc <= current_ccc + 0.05:
        notes.append("Even true T1 has limited total-T3 bridge value on this cohort; total T3 is dominated by non-axial domains.")
    else:
        notes.append("True T1 has privileged bridge value, supporting target-decomposition analysis but not a deployable T3 feature.")
    return notes


def text_blob(route: dict[str, Any]) -> str:
    fields = [
        route.get("name"),
        route.get("access_status"),
        route.get("label"),
        route.get("modality"),
        route.get("status"),
        route.get("verdict"),
    ]
    sources = route.get("sources") or []
    return " ".join(str(value or "") for value in fields + sources).lower()


def route_scores(route: dict[str, Any], readiness_priority_by_name: dict[str, int]) -> dict[str, Any]:
    text = text_blob(route)
    status = str(route.get("status") or "").lower()
    verdict_text = str(route.get("verdict") or "").lower()
    direct = bool(route.get("direct_t1_t3_eligible"))
    readiness_priority = readiness_priority_by_name.get(str(route.get("name") or ""))
    already_closed = any(
        token in status
        for token in [
            "zero_shot_complete",
            "skipped",
            "hard_stop",
            "wrong_modality",
            "local_feature_addition_dead",
            "no_public_aligned_sensor_data",
            "not_direct",
        ]
    ) or any(
        token in verdict_text
        for token in [
            "screen failed",
            "gate fail",
            "partial clinical+wrist external validity only",
            "external-validity evidence only",
            "no internal canonical",
            "stopped before scoring",
            "underpowered",
            "not a t1/t3",
            "not a t1/t3 ccc",
            "not a direct",
            "no zero-shot",
        ]
    )
    if readiness_priority is not None and direct:
        already_closed = False
    access_gated = any(token in text for token in ["gated", "request", "dua", "application", "proposal", "membership"])
    public = "public" in str(route.get("access_status", "")).lower()

    label_score = 1.0 if direct else 0.0
    if "item" in text or "subitem" in text or "part iii" in text or "mds-updrs" in text:
        label_score = max(label_score, 0.7)
    if "tremor" in text and not direct:
        label_score = min(label_score, 0.35)

    protocol_score = 0.0
    if "watch" in text or "wrist" in text or "apple" in text or "verily" in text:
        protocol_score += 0.25
    if any(token in text for token in ["finger", "hand", "pronation", "upper", "vme", "mDS-UPDRS Part III".lower()]):
        protocol_score += 0.35
    if "tremor" in text or "rigidity" in text or "apdm" in text:
        protocol_score += 0.20
    if "lower-back" in text or "lower back" in text or "gait" in text or "axivity" in text:
        protocol_score += 0.15
    if "ppmi" in text or "personalized parkinson" in text or "pd virtual motor exam" in text:
        protocol_score += 0.20
    if "watch-pd" in text or "apdm" in text:
        protocol_score += 0.15
    protocol_score = min(protocol_score, 1.0)

    if already_closed:
        access_score = 0.10
    elif access_gated and direct:
        access_score = 0.65
    elif public and direct:
        access_score = 0.75
    elif access_gated:
        access_score = 0.30
    else:
        access_score = 0.20

    compute_ready_now = public and direct and not access_gated and not already_closed
    if compute_ready_now:
        first_allowed_action = "write read-only probe before any preregistration"
    elif access_gated and direct:
        first_allowed_action = "complete access request, then read-only schema probe after approval"
    elif already_closed:
        first_allowed_action = "no compute; retain as documented external-validity evidence"
    else:
        first_allowed_action = "document only; no scaffold or remote job"

    priority_bonus = 0.0
    if readiness_priority is not None:
        priority_bonus = max(0.0, 7.0 - float(readiness_priority)) * 0.05
    opportunity = (0.40 * protocol_score) + (0.35 * access_score) + (0.25 * label_score) + priority_bonus
    if not direct:
        opportunity *= 0.25
    if already_closed:
        opportunity *= 0.35

    return {
        "name": route.get("name"),
        "direct_t1_t3_eligible": direct,
        "already_closed_or_external_only": already_closed,
        "compute_ready_now": compute_ready_now,
        "access_score": round(access_score, 3),
        "protocol_gap_coverage_score": round(protocol_score, 3),
        "label_score": round(label_score, 3),
        "opportunity_score": round(opportunity, 3),
        "access_readiness_priority": readiness_priority,
        "first_allowed_action": first_allowed_action,
        "status": route.get("status"),
        "access_status": route.get("access_status"),
        "verdict": route.get("verdict"),
    }


def external_route_report() -> dict[str, Any]:
    routes = read_json(EXTERNAL_ROUTES_PATH).get("routes", [])
    readiness_routes = read_json(ACCESS_READINESS_PATH).get("routes", [])
    readiness_priority_by_name = {
        str(route.get("name")): int(route.get("priority"))
        for route in readiness_routes
        if route.get("name") is not None and route.get("priority") is not None
    }
    scored = [route_scores(route, readiness_priority_by_name) for route in routes]
    scored.sort(key=lambda row: row["opportunity_score"], reverse=True)
    compute_ready = [row for row in scored if row["compute_ready_now"]]
    return {
        "n_routes_scored": len(scored),
        "compute_ready_routes_before_access": len(compute_ready),
        "top_routes": scored[:10],
        "policy": "Scoring is for route prioritization only. It cannot authorize download, scaffold, preregistration, or model runs for gated routes.",
    }


def residual_stop_rule_summary() -> dict[str, Any]:
    residual = read_json(RESIDUAL_ANATOMY_PATH)
    domain = read_json(DOMAIN_RESIDUAL_PATH)
    item = read_json(ITEM_RESIDUAL_PATH)
    blocker = read_json(BLOCKER_ACTIONS_PATH)
    access = read_json(ACCESS_READINESS_PATH)
    recent = read_json(RECENT_WEB_LEADS_PATH)
    top_domains = sorted(
        domain.get("domain_summary", []),
        key=lambda row: abs(row.get("corr_domain_with_residual_pred_minus_true") or 0.0),
        reverse=True,
    )[:5]
    top_items = sorted(
        item.get("item_rows", []),
        key=lambda row: row.get("abs_corr_item_with_residual") or 0.0,
        reverse=True,
    )[:8]
    return {
        "current_t3": residual.get("overall_metrics", {}),
        "top_residual_domains": [
            {
                "domain": row.get("domain"),
                "items": row.get("items"),
                "deployable_proxy_candidate": row.get("deployable_proxy_candidate"),
                "corr_with_residual": row.get("corr_domain_with_residual_pred_minus_true"),
                "oracle_delta_ccc_vs_base": row.get("oracle_delta_ccc_vs_base"),
            }
            for row in top_domains
        ],
        "top_residual_items": [
            {
                "item": row.get("item"),
                "name": row.get("name"),
                "weargait_observable": row.get("weargait_observable"),
                "abs_corr_with_residual": row.get("abs_corr_item_with_residual"),
                "oracle_delta_ccc_vs_base": row.get("loo_privileged_oracle", {}).get("delta_ccc_vs_base"),
            }
            for row in top_items
        ],
        "blocker_summary": {
            "local_weargait_only_model_actions_remaining": blocker.get("summary", {}).get("local_model_actions_remaining"),
            "unclassified_blockers": blocker.get("summary", {}).get("unclassified_blockers"),
            "ambiguous_blockers": blocker.get("summary", {}).get("ambiguous_blockers"),
        },
        "access_readiness_summary": access.get("summary", {}),
        "recent_web_leads_summary": recent.get("summary", {}),
    }


def derive_decision(report: dict[str, Any]) -> dict[str, Any]:
    scaffolds = report["t1_scaffold_diagnostic"]["reports"]
    best_scaffold_delta = max(row["delta_scaffold_ccc_vs_current_intersection"] for row in scaffolds)
    route_report = report["external_route_prioritization"]
    stop_summary = report["residual_stop_rule_summary"]
    local_actions = stop_summary["blocker_summary"].get("local_weargait_only_model_actions_remaining")
    compute_ready = route_report["compute_ready_routes_before_access"]
    if best_scaffold_delta < 0.025 and local_actions in (0, None) and compute_ready == 0:
        verdict = "no_local_t3_ceiling_break_route_after_scout"
    else:
        verdict = "diagnostic_signal_requires_human_review_before_any_action"
    return {
        "verdict": verdict,
        "best_t1_scaffold_delta_ccc_vs_current_intersection": float(best_scaffold_delta),
        "compute_ready_external_routes_before_access": int(compute_ready),
        "next_action": KIMI_CONSULT_SUMMARY["highest_leverage_next_action"],
        "blocked_actions": KIMI_CONSULT_SUMMARY["absolute_prohibitions"],
    }


def write_markdown(report: dict[str, Any]) -> None:
    decision = report["decision"]
    lines = [
        "# T3 Ceiling Research Scout",
        "",
        "Diagnostic-only decision audit. No preregistration, LOOCV, lockbox, or canonical update is authorized by this file.",
        "",
        "## Decision",
        "",
        f"- Verdict: `{decision['verdict']}`",
        f"- Best T1-scaffold delta vs current intersection: `{decision['best_t1_scaffold_delta_ccc_vs_current_intersection']:.4f}` CCC",
        f"- Compute-ready external routes before access: `{decision['compute_ready_external_routes_before_access']}`",
        f"- Next action: {decision['next_action']}",
        "",
        "## T1 Scaffold Diagnostic",
        "",
        "This is an OOF-level diagnostic and is not fully nested. It is a negative-control bridge, not a candidate model.",
        "",
        "| Source | N | Current CCC | Scaffold CCC | True-T1 Oracle CCC | Delta vs Current |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in report["t1_scaffold_diagnostic"]["reports"]:
        cur = row["current_t3_metrics_on_intersection"]["ccc"]
        sca = row["t1_oof_prediction_to_t3_loo_ridge"]["ccc"]
        oracle = row["true_t1_to_t3_privileged_oracle"]["ccc"]
        lines.append(
            f"| {row['label']} | {row['n_intersection_with_iter47_t3']} | {cur:.4f} | {sca:.4f} | {oracle:.4f} | {row['delta_scaffold_ccc_vs_current_intersection']:.4f} |"
        )
    lines.extend(["", "## Residual Stop Rule", ""])
    current = report["residual_stop_rule_summary"]["current_t3"]
    lines.extend(
        [
            f"- Current corrected T3 CCC: `{current.get('ccc', float('nan')):.4f}`; MAE: `{current.get('mae', float('nan')):.4f}`; residual corr with true severity: `{current.get('residual_corr_with_true', float('nan')):.4f}`.",
            "- Top residual burden remains non-gait/upper-limb/rigidity content; these are privileged clinical labels, not deployable WearGait features.",
            "",
            "## Top External Routes",
            "",
            "| Route | Score | Access | Protocol Coverage | First Allowed Action |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for row in report["external_route_prioritization"]["top_routes"][:8]:
        lines.append(
            f"| {row['name']} | {row['opportunity_score']:.3f} | {row['access_score']:.3f} | {row['protocol_gap_coverage_score']:.3f} | {row['first_allowed_action']} |"
        )
    lines.extend(["", "## Kimi Consult", ""])
    lines.append(f"- Verdict: `{KIMI_CONSULT_SUMMARY['verdict']}`")
    lines.append(f"- Highest-leverage next action: {KIMI_CONSULT_SUMMARY['highest_leverage_next_action']}")
    lines.extend(["", "## Prohibited", ""])
    for blocked in KIMI_CONSULT_SUMMARY["absolute_prohibitions"]:
        lines.append(f"- {blocked}")
    lines.extend(["", "## Fresh Source Notes", ""])
    for note in FRESH_SOURCE_NOTES:
        lines.append(f"- {note['name']}: {note['finding']} ({note['source']})")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    require_files()
    report: dict[str, Any] = {
        "script": "audit_t3_ceiling_research_scout.py",
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": "diagnostic_only_route_prioritization_no_model_promotion",
        "inputs": [str(path.relative_to(ROOT)) for path in REQUIRED_FILES],
        "fresh_source_notes": FRESH_SOURCE_NOTES,
        "kimi_consult_summary": KIMI_CONSULT_SUMMARY,
        "t1_scaffold_diagnostic": scaffold_report(),
        "residual_stop_rule_summary": residual_stop_rule_summary(),
        "external_route_prioritization": external_route_report(),
    }
    report["decision"] = derive_decision(report)
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(report)
    print(json.dumps(report["decision"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
