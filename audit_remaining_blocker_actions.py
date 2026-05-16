#!/usr/bin/env python3
"""Classify current goal blockers by the next valid action boundary.

This is a decision audit, not a success marker. It reads the current-state
verifier output and makes every blocker explicit as one of:

- stopped internal modeling evidence,
- provenance/raw-data recovery blocked,
- external-only result evidence,
- user/data-owner access required,
- not T1/T3 eligible,
- or caveated T1 candidate evidence.

The audit fails if any current blocker is unclassified or if a WearGait-only
model/lockbox action remains locally justified by the current evidence.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
SOURCE_JSON = RESULTS / "current_goal_state_verification_20260508.json"
OUT_JSON = RESULTS / "remaining_blocker_action_audit_20260509.json"
OUT_MD = RESULTS / "remaining_blocker_action_audit_20260509.md"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


RULES: list[dict[str, Any]] = [
    {
        "id": "t3_corrected_headline_unbroken",
        "patterns": [r"valid-range-corrected CCC is 0\.3784"],
        "category": "internal_t3_stopped_by_current_evidence",
        "action_type": "no_local_weargait_model_run",
        "reason": "Current corrected T3 headline is below the superseded historical target-contaminated result, with no improved corrected lockbox.",
        "recommended_next_action": "Do not run another corrected-target WearGait-only lockbox without a new target representation or new labeled data.",
    },
    {
        "id": "t3_residual_anatomy_tail_compression",
        "patterns": [r"residual-anatomy", r"tail compression"],
        "category": "internal_t3_stopped_by_current_evidence",
        "action_type": "no_local_weargait_model_run",
        "reason": "The residual anatomy points to target-domain structure and tail compression, not a missing scalar feature.",
        "recommended_next_action": "Use this as paper/error-anatomy evidence; do not retry feature fishing or calibration as a ceiling route.",
    },
    {
        "id": "t3_ccc_rescale_trap",
        "patterns": [r"CCC-rescale", r"worsens MAE"],
        "category": "metric_accounting_trap",
        "action_type": "disclosure_only_no_model_run",
        "reason": "OOF variance matching is cosmetic, not a nested reportable model.",
        "recommended_next_action": "Keep as a guardrail against CCC-only post-hoc transforms.",
    },
    {
        "id": "headline_influence_tail_concentration",
        "patterns": [r"headline influence", r"severity-tail"],
        "category": "diagnostic_no_single_subject_redline",
        "action_type": "disclosure_only_no_model_run",
        "reason": "Influence is tail-concentrated but not a single-subject artifact that can be repaired by deletion.",
        "recommended_next_action": "Disclose influence structure; do not do post-hoc cohort surgery.",
    },
    {
        "id": "t3_domain_residual_unobservable",
        "patterns": [r"domain residual", r"unobservable_non_gait"],
        "category": "privileged_oracle_not_deployable",
        "action_type": "no_local_weargait_model_run",
        "reason": "The best explanatory domains require true clinical labels and are not deployable WearGait features.",
        "recommended_next_action": "Use as observability-limit evidence.",
    },
    {
        "id": "t3_item_residual_unobservable",
        "patterns": [r"item-level residual", r"non-WearGait-observable"],
        "category": "privileged_oracle_not_deployable",
        "action_type": "no_local_weargait_model_run",
        "reason": "Largest residual associations are non-observable Part III items, so another WearGait-only scalar/calibration screen is unjustified.",
        "recommended_next_action": "Use as observability-limit evidence.",
    },
    {
        "id": "t3_clinical_dependency",
        "patterns": [r"clinical-dependency", r"intercept/IMU-only CCC"],
        "category": "clinical_plus_imu_boundary",
        "action_type": "disclosure_only_no_model_run",
        "reason": "Corrected T3 depends heavily on clinical/intake covariates; pure IMU-only performance is much lower.",
        "recommended_next_action": "Label corrected T3 as clinical/intake plus IMU, not pure wearable deployment.",
    },
    {
        "id": "t3_dst_provenance_caveat",
        "patterns": [r"dst_\*", r"no-`dst_\*` sensitivity"],
        "category": "provenance_caveat_not_load_bearing",
        "action_type": "disclosure_only_no_model_run",
        "reason": "The historical non-fold-local distiller features are not load-bearing for the corrected T3 metric.",
        "recommended_next_action": "Disclose provenance caveat; no model rerun is justified by this alone.",
    },
    {
        "id": "ablation_v3_cache_missing_manifest",
        "patterns": [r"ablation_v3_features\.csv", r"missing-manifest"],
        "category": "provenance_raw_data_blocked",
        "action_type": "requires_weargait_raw_data_restore",
        "reason": "The live V2 cache remains diagnostic-only without clean provenance.",
        "recommended_next_action": "Restore exact WearGait raw/control inputs or keep current cache-dependent claims diagnostic-only.",
    },
    {
        "id": "ablation_v3_regeneration_blocked",
        "patterns": [r"regeneration probe failed", r"control clinical data"],
        "category": "provenance_raw_data_blocked",
        "action_type": "requires_weargait_raw_data_restore",
        "reason": "Regeneration is blocked by missing local/remote raw inputs, not by modeling code.",
        "recommended_next_action": "Restore control clinical CSVs, control sensor CSVs, and walkway metrics before attempting regeneration.",
    },
    {
        "id": "weargait_synapse_recovery_no_token",
        "patterns": [r"syn55105521", r"no Synapse token"],
        "category": "provenance_credentials_blocked",
        "action_type": "requires_user_credentials_or_confirmation",
        "reason": "The recovery path is known, but credentials and large-download confirmation are absent.",
        "recommended_next_action": "Provide Synapse credentials/config and explicit confirmation before any large control-CSV recovery.",
    },
    {
        "id": "fogstar_stage1_screen_failed",
        "patterns": [r"FoG-STAR iter38", r"failed its gate"],
        "category": "external_augmentation_dead",
        "action_type": "no_local_weargait_model_run",
        "reason": "The public external Stage-1 augmentation screen failed; no lockbox is warranted.",
        "recommended_next_action": "Keep FoG-STAR as external-validity evidence only.",
    },
    {
        "id": "fogstar_external_only",
        "patterns": [r"FoG-STAR iter39", r"external-validity evidence only"],
        "category": "external_result_only",
        "action_type": "paper_transportability_only",
        "reason": "This is external zero-shot evidence, not internal WearGait-PD improvement.",
        "recommended_next_action": "Report only as external transportability context.",
    },
    {
        "id": "iter40_local_residual_failed",
        "patterns": [r"iter40 local-residual", r"failed"],
        "category": "internal_t3_failed_gate",
        "action_type": "no_local_weargait_model_run",
        "reason": "The wildcard local-residual smoother failed the 5-fold promotion gate.",
        "recommended_next_action": "Do not retry KNN/PCA/local residual smoothers on this architecture.",
    },
    {
        "id": "iter50_lowdf_failed",
        "patterns": [r"iter50 low-degree", r"0\.3083"],
        "category": "internal_t3_failed_gate",
        "action_type": "no_local_weargait_model_run",
        "reason": "The pre-registered low-degree nested mix underperformed the corrected-target baseline.",
        "recommended_next_action": "Do not retry low-degree clinical/IMU mixers without genuinely new predictors.",
    },
    {
        "id": "iter42_proration_failed",
        "patterns": [r"iter42 primary", r"not promotable"],
        "category": "target_hygiene_sensitivity_failed",
        "action_type": "disclosure_only_no_model_run",
        "reason": "The primary target-proration rule failed and loose sensitivity is not canonical.",
        "recommended_next_action": "Keep iter47 valid-range target as current T3 audit truth.",
    },
    {
        "id": "t3_slotf_boundary_lift_not_promoted",
        "patterns": [r"T3 Slot F CQR-width", r"frac>full >= 0\.95"],
        "category": "deployable_secondary_boundary_not_promoted",
        "action_type": "paper_uncertainty_only",
        "reason": "Slot F is a y-free deployable-secondary boundary result, but its seed-101 replication still fails the promotion frac gate and cannot update the full-cohort T3 headline.",
        "recommended_next_action": "Report as a boundary-lift/deployable-secondary result, not as a full-cohort ceiling break; do not rerun local abstention variants without new data or a new pre-registered estimand.",
    },
    {
        "id": "t3_s13_s15_transfer_not_promoted",
        "patterns": [r"T3 S13/S15", r"below 0\.95"],
        "category": "deployable_secondary_boundary_not_promoted",
        "action_type": "paper_uncertainty_only",
        "reason": "The PH/MFDFA transfer extension and y-free retained-secondary variant are informative near-misses but do not pass full-cohort or retained-bootstrap promotion gates.",
        "recommended_next_action": "Record as a non-promoted pro-results closure; do not rerun local T3 retained-abstention variants without new data or a new preregistered estimand.",
    },
    {
        "id": "cops_external_only",
        "patterns": [r"COPS iter49", r"external-validity evidence only"],
        "category": "external_result_only",
        "action_type": "paper_transportability_only",
        "reason": "COPS is an external transportability result and cannot update the internal T3 headline.",
        "recommended_next_action": "Report as external row only.",
    },
    {
        "id": "tlvmc_external_only",
        "patterns": [r"TLVMC/DeFOG iter51", r"external outcome"],
        "category": "external_result_only",
        "action_type": "paper_transportability_only",
        "reason": "TLVMC/DeFOG is external-only, with compressed predictions.",
        "recommended_next_action": "Report as external row only.",
    },
    {
        "id": "pdfe_external_only",
        "patterns": [r"PDFE turning-in-place iter52", r"external-validity evidence only"],
        "category": "external_result_only",
        "action_type": "paper_transportability_only",
        "reason": "PDFE is protocol-specific external evidence; WearGait transfer is negative or weak.",
        "recommended_next_action": "Report as external row only.",
    },
    {
        "id": "parkinsonathome_hard_stop_no_score",
        "patterns": [r"Parkinson@Home iter53", r"hard-stopped before scoring"],
        "category": "external_route_stopped_before_scoring",
        "action_type": "no_prereg_no_rerun_same_policy",
        "reason": "The public direct T3 route did not meet the pre-registered minimum feature-readable OFF-subject count, so no metric exists.",
        "recommended_next_action": "Do not rerun iter53 under the same preregistration; any shorter-window or fallback policy requires a fresh preregistration and remains external-only.",
    },
    {
        "id": "hssayeni_dua_blocked",
        "patterns": [r"Hssayeni/MJFF", r"DUA-blocked"],
        "category": "external_access_required",
        "action_type": "requires_user_or_data_owner_access",
        "reason": "Synapse DUA approval is a regulatory/access gate.",
        "recommended_next_action": "User-side Synapse DUA approval, then run the existing iter26 probe.",
    },
    {
        "id": "ppmi_access_required",
        "patterns": [r"PPMI/Verily", r"DUA/application"],
        "category": "external_access_required",
        "action_type": "requires_user_or_data_owner_access",
        "reason": "PPMI requires qualified-researcher access before any schema probe.",
        "recommended_next_action": "Apply for PPMI access; then do read-only schema inspection.",
    },
    {
        "id": "watchpd_access_required",
        "patterns": [r"WATCH-PD", r"C-Path"],
        "category": "external_access_required",
        "action_type": "requires_user_or_data_owner_access",
        "reason": "WATCH-PD DHT data require C-Path/Steering Committee access and row-level schema.",
        "recommended_next_action": "Request access; no scaffold before files/schema exist.",
    },
    {
        "id": "icicle_access_required",
        "patterns": [r"ICICLE-PD/ICICLE-GAIT", r"request-gated"],
        "category": "external_access_required",
        "action_type": "requires_user_or_data_owner_access",
        "reason": "ICICLE is request-gated.",
        "recommended_next_action": "Submit data request; then schema probe only after access.",
    },
    {
        "id": "cns_access_required",
        "patterns": [r"CNS Portugal/Lobo", r"request-gated"],
        "category": "external_access_required",
        "action_type": "requires_user_or_data_owner_access",
        "reason": "CNS Portugal/Lobo data are request-gated.",
        "recommended_next_action": "Request data/schema from author or CNS before scaffolding.",
    },
    {
        "id": "mobilised_watchlist",
        "patterns": [r"Mobilise-D", r"release/schema watch"],
        "category": "external_watchlist_not_compute_ready",
        "action_type": "monitor_or_request_no_scaffold",
        "reason": "TVS is not the clinical route and CVS row-level release/schema is unavailable.",
        "recommended_next_action": "Monitor/request CVS release; no code until row-level wearable plus MDS-UPDRS data exist.",
    },
    {
        "id": "harmonized_accel_not_eligible",
        "patterns": [r"Harmonized Upper/Lower Limb", r"no confirmed Part III/T1"],
        "category": "not_t1_t3_eligible",
        "action_type": "no_prereg_no_download",
        "reason": "No confirmed total Part III or T1 target route is visible.",
        "recommended_next_action": "Do not scaffold or download for this objective.",
    },
    {
        "id": "monipar_bioclite_not_eligible",
        "patterns": [r"Monipar/BIOCLITE", r"neither has total T3"],
        "category": "not_t1_t3_eligible",
        "action_type": "no_prereg_no_download",
        "reason": "They are subitem datasets lacking total T3 and full T1 9-14 composite.",
        "recommended_next_action": "Do not preregister or download for this objective.",
    },
    {
        "id": "zenodo_14848598_not_eligible",
        "patterns": [r"Zenodo 14848598", r"not raw wearable IMU"],
        "category": "not_t1_t3_eligible",
        "action_type": "no_prereg_no_download",
        "reason": "The dataset is derived CSF/clinical/gait-summary, not auditable raw wearable alignment.",
        "recommended_next_action": "Do not scaffold or download for this objective.",
    },
    {
        "id": "fay_karmon_request_only",
        "patterns": [r"Fay-Karmon", r"request-only"],
        "category": "external_access_required_small_or_schema_hidden",
        "action_type": "requires_user_or_data_owner_access",
        "reason": "Small-N, schema-hidden, and no T1 route is visible.",
        "recommended_next_action": "Optional author request only; no scaffold before approval and schema.",
    },
    {
        "id": "marital_dyad_request_only",
        "patterns": [r"Marital-dyad", r"request-only"],
        "category": "external_access_required_small_or_schema_hidden",
        "action_type": "requires_user_or_data_owner_access",
        "reason": "Small-N daily-life dyad data, not structured gait/balance, and no T1 route is visible.",
        "recommended_next_action": "Optional author request only; no scaffold before approval and schema.",
    },
    {
        "id": "ppp_rdsrc_gated",
        "patterns": [r"Personalized Parkinson Project", r"RDSRC-gated"],
        "category": "external_access_required",
        "action_type": "requires_user_or_data_owner_access",
        "reason": "The route is gated and schema-hidden.",
        "recommended_next_action": "Request RDSRC access; no scaffold before approval and schema.",
    },
    {
        "id": "t1_iter34_hygiene_candidate_not_clean_break",
        "patterns": [r"T1 hygiene-corrected iter34", r"above the canonical floor"],
        "category": "t1_candidate_caveated",
        "action_type": "candidate_disclosure_no_posthoc_lockbox",
        "reason": "The hygiene-corrected iter34 result is the strongest current T1 candidate but remains a caveated candidate rather than a clean canonical ceiling break.",
        "recommended_next_action": "Frame as strongest caveated candidate/post-publication replication target; do not rerun post-hoc variants.",
    },
    {
        "id": "t1_iter34_p2_caveat",
        "patterns": [r"T1 iter34", r"P2 noisy-test"],
        "category": "t1_candidate_caveated",
        "action_type": "candidate_disclosure_no_posthoc_lockbox",
        "reason": "The candidate is above the floor but does not have a clean all-null-gates pass.",
        "recommended_next_action": "Frame as strongest caveated candidate, not canonical replacement.",
    },
    {
        "id": "t1_iter34_aux_caveat",
        "patterns": [r"auxiliary-label/order caveat", r"No post-hoc N=92"],
        "category": "t1_candidate_caveated",
        "action_type": "candidate_disclosure_no_posthoc_lockbox",
        "reason": "The auxiliary-label/order issue is documented and low-materiality; rerunning after discovery would be cohort surgery.",
        "recommended_next_action": "Document the caveat; do not run a post-hoc N=92 lockbox.",
    },
    {
        "id": "t1_iter46_failed",
        "patterns": [r"T1 iter46", r"did not break iter34"],
        "category": "internal_t1_followup_failed",
        "action_type": "no_local_weargait_model_run",
        "reason": "The robustification follow-up did not break iter34 and did not strictly clear iter12.",
        "recommended_next_action": "Stop this T1 base-subset branch.",
    },
]


LOCAL_MODEL_ACTION_TYPES = {
    "local_model_action_allowed",
}


def matches(rule: dict[str, Any], blocker: str) -> bool:
    return all(re.search(pattern, blocker, flags=re.IGNORECASE) for pattern in rule["patterns"])


def classify(blocker: str) -> dict[str, Any]:
    matched = [rule for rule in RULES if matches(rule, blocker)]
    if not matched:
        return {
            "rule_id": "unclassified",
            "category": "unclassified",
            "action_type": "needs_manual_triage",
            "local_model_action_allowed": True,
            "requires_user_or_external_access": False,
            "reason": "No rule matched this blocker.",
            "recommended_next_action": "Manually classify before taking action.",
        }
    if len(matched) > 1:
        # Exact current blockers are expected to be unique; preserve all matches
        # so future wording drift is easy to inspect.
        best = matched[0]
        multi = [rule["id"] for rule in matched]
    else:
        best = matched[0]
        multi = []
    action_type = best["action_type"]
    return {
        "rule_id": best["id"],
        "multiple_rule_matches": multi,
        "category": best["category"],
        "action_type": action_type,
        "local_model_action_allowed": action_type in LOCAL_MODEL_ACTION_TYPES,
        "requires_user_or_external_access": action_type
        in {
            "requires_user_or_data_owner_access",
            "requires_user_credentials_or_confirmation",
        },
        "reason": best["reason"],
        "recommended_next_action": best["recommended_next_action"],
    }


def build_report() -> dict[str, Any]:
    verifier = load_json(SOURCE_JSON)
    blockers = verifier.get("blockers", [])

    rows = []
    for idx, blocker in enumerate(blockers, start=1):
        row = {"index": idx, "blocker": blocker}
        row.update(classify(blocker))
        rows.append(row)

    unmatched = [row for row in rows if row["category"] == "unclassified"]
    ambiguous = [row for row in rows if row.get("multiple_rule_matches")]
    local_model_actions = [row for row in rows if row.get("local_model_action_allowed")]
    access_required = [row for row in rows if row.get("requires_user_or_external_access")]
    raw_data_required = [
        row
        for row in rows
        if row.get("action_type")
        in {"requires_weargait_raw_data_restore", "requires_user_credentials_or_confirmation"}
    ]

    category_counts = Counter(row["category"] for row in rows)
    action_type_counts = Counter(row["action_type"] for row in rows)

    source_hard_failures = verifier.get("hard_failures", [])
    source_hard_failures_excluding_self = [
        failure
        for failure in source_hard_failures
        if failure.get("name") != "remaining blocker action audit leaves no local WearGait-only model action"
    ]

    hard_failures = []
    if verifier.get("current_state_verified") is not True and source_hard_failures_excluding_self:
        hard_failures.append(
            {
                "type": "source_verifier_not_current",
                "message": "Source verifier has hard failures outside the remaining-blocker self-check.",
                "source_hard_failures_excluding_self": source_hard_failures_excluding_self,
            }
        )
    if unmatched:
        hard_failures.append(
            {
                "type": "unclassified_blockers",
                "n": len(unmatched),
                "rows": unmatched,
            }
        )
    if ambiguous:
        hard_failures.append(
            {
                "type": "ambiguous_blocker_classification",
                "n": len(ambiguous),
                "rows": ambiguous,
            }
        )
    if local_model_actions:
        hard_failures.append(
            {
                "type": "local_model_actions_remain",
                "n": len(local_model_actions),
                "rows": local_model_actions,
            }
        )

    return {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_remaining_blocker_actions.py",
        "source": str(SOURCE_JSON.relative_to(ROOT)),
        "source_current_state_verified": verifier.get("current_state_verified"),
        "source_goal_complete": verifier.get("goal_complete"),
        "source_blocker_count": len(blockers),
        "policy": (
            "Every current blocker must map to a non-redundant next-action boundary. "
            "A new WearGait-only model or lockbox is allowed only if a blocker is "
            "classified as local_model_action_allowed; the current audit expects zero."
        ),
        "passed": not hard_failures,
        "category_counts": dict(sorted(category_counts.items())),
        "action_type_counts": dict(sorted(action_type_counts.items())),
        "unmatched_blockers": unmatched,
        "ambiguous_blockers": ambiguous,
        "local_model_actions": local_model_actions,
        "access_required_blockers": access_required,
        "raw_data_required_blockers": raw_data_required,
        "recommended_next_actions": [
            "Pursue user/data-owner access for gated external cohorts before any new external scaffold: Hssayeni/MJFF, PPMI/Verily, WATCH-PD, ICICLE-PD/ICICLE-GAIT, CNS Portugal/Lobo, Personalized Parkinson Project / PD-VME, or optional small request-only cohorts.",
            "Restore WearGait raw/control inputs and Synapse credentials only if the goal is V2 cache provenance regeneration; this is not a new CCC-breaking model action by itself.",
            "Continue paper/provenance hardening and claim guards as needed.",
            "Do not launch another WearGait-only T1/T3 model family from the current evidence without new labeled data or a new pre-registered target representation.",
        ],
        "hard_failures": hard_failures,
        "rows": rows,
    }


def write_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Remaining Blocker Action Audit — 2026-05-09",
        "",
        f"Passed: `{str(report['passed']).lower()}`",
        f"Source verifier goal complete: `{str(report['source_goal_complete']).lower()}`",
        f"Source blockers: `{report['source_blocker_count']}`",
        f"Local WearGait-only model actions remaining: `{len(report['local_model_actions'])}`",
        f"Unclassified blockers: `{len(report['unmatched_blockers'])}`",
        "",
        "## Policy",
        "",
        report["policy"],
        "",
        "## Counts",
        "",
        "### Categories",
        "",
    ]
    for key, value in report["category_counts"].items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "### Action Types", ""])
    for key, value in report["action_type_counts"].items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(
        [
            "",
            "## Recommended Next Actions",
            "",
        ]
    )
    for action in report["recommended_next_actions"]:
        lines.append(f"- {action}")
    lines.extend(
        [
            "",
            "## Blocker Classification",
            "",
            "| # | Category | Action type | Blocker |",
            "|---:|---|---|---|",
        ]
    )
    for row in report["rows"]:
        blocker = row["blocker"].replace("|", "\\|")
        lines.append(
            f"| {row['index']} | `{row['category']}` | `{row['action_type']}` | {blocker} |"
        )
    if report["hard_failures"]:
        lines.extend(["", "## Hard Failures", ""])
        for failure in report["hard_failures"]:
            lines.append(f"- `{failure['type']}`: {failure.get('message', failure.get('n'))}")
    return "\n".join(lines) + "\n"


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    report = build_report()
    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    OUT_MD.write_text(write_markdown(report), encoding="utf-8")
    print(f"Wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"Wrote {OUT_MD.relative_to(ROOT)}")
    print(f"passed={report['passed']}")
    print(f"source_blocker_count={report['source_blocker_count']}")
    print(f"local_model_actions={len(report['local_model_actions'])}")
    print(f"unmatched_blockers={len(report['unmatched_blockers'])}")
    if report["hard_failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
