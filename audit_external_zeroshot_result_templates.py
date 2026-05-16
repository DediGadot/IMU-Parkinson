#!/usr/bin/env python3
"""Audit generic all-route external zero-shot result templates and validator."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pd_imu.datasets import external_schema_probe_specs


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
SCRIPT = ROOT / "scripts" / "write_external_zeroshot_result_templates.py"
VALIDATOR = ROOT / "scripts" / "validate_external_zeroshot_result_record.py"
TEMPLATES_JSON = RESULTS / "external_zeroshot_result_templates_20260515.json"
TEMPLATES_MD = RESULTS / "external_zeroshot_result_templates_20260515.md"
TEMPLATE_DIR = RESULTS / "external_zeroshot_result_templates_20260515"
SYNTH_DIR = RESULTS / "external_zeroshot_result_templates_synthetic"
FORMULA_SHA_AUDIT = RESULTS / "external_formula_sha_templates_audit_20260515.json"
OUT_JSON = RESULTS / "external_zeroshot_result_templates_audit_20260515.json"
OUT_MD = RESULTS / "external_zeroshot_result_templates_audit_20260515.md"

EXPECTED_ROUTE_IDS = [
    "ppmi_verily",
    "ppp_pd_vme",
    "watchpd",
    "cns_portugal_lobo",
    "hssayeni_mjff",
    "icicle_gait",
]
EXPECTED_RESULT_STAGE = "post_score_external_zero_shot_result_record"
EXPECTED_TEMPLATE_STATUS = "template_complete_outside_git_after_external_zero_shot_scoring"
EXPECTED_POST_SCORE_REPORTING_WORKFLOW_STEP_IDS = [
    "validate_zeroshot_result_record",
    "audit_external_result_claim_labeling",
    "audit_prompt_objective_evidence",
    "verify_current_goal_state",
]
PRIOR_GATE_KEYS = [
    "approved_access_recorded",
    "schema_probe_metadata_recorded",
    "target_free_manifest_preflight_passed",
    "formula_sha_record_preflight_passed",
]
FALSE_BOUNDARY_KEYS = {
    "internal_canonical_update_allowed",
    "protected_data_included",
    "credentials_or_tokens_included",
    "raw_rows_or_samples_included",
    "feature_matrix_included",
    "target_values_included",
    "row_predictions_included",
    "model_predictions_included",
    "local_paths_included",
    "preregistration_written",
}
PPMI_K250_FORMULA_SHA256 = (
    "489ca6bbc96520c2ea56cc53ee52b03542bec799f9bd41c34d9c9ef5b61ebee4"
)
PPMI_BLUEPRINT_SHA256 = (
    "4540fbc00a3bb92b6bedca34e954bb0e8ae00cbee30ee6f9651c56229591e13f"
)
PPMI_REQUIRED_LOCKED_FORMULA_COMPONENTS = {
    "small fixed TopoFractal PH/MFDFA branch",
    "canonical comparator",
    "separate fixed K=250 sklearn-GB branch for T3 only",
    "no omnibus feature expansion",
    "no cross-branch adaptive stacking before zero-shot results",
}
PPMI_ROUTE_SPECIFIC_TRACKS = {
    "A": "weargait_trained_wrist_topofractal_zeroshot",
    "B": "weargait_trained_clinical_plus_wrist_zeroshot",
    "C": "ppmi_only_subject_grouped_sanity",
    "D": "augmentation_screen_after_zero_shot_only",
}
PPMI_X4_V3_GSP_COMPATIBILITY_POLICY = {
    "status": "excluded_for_wrist_only_ppmi_zero_shot",
    "requires_sensor_layout": "WearGait-compatible 13-node anatomical IMU graph",
    "can_enter_formula_if": (
        "approved schema probe proves comparable multi-node anatomical sensors "
        "before formula_sha256 freeze"
    ),
    "external_label_selection_allowed": False,
}
FORBIDDEN_SNIPPETS = [
    ".access_",
    "_submission.json",
    "_approval.json",
    "_schema_probe.json",
    "LOCAL_COMPLETED",
    "password",
    "api_key",
    "private_key",
    "secret_key",
    "raw sample",
    "raw rows",
]


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{rel(path)} must contain a JSON object")
    return payload


def run_writer() -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=120,
    )
    parsed: dict[str, Any] | None = None
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        parsed = None
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "parsed": parsed,
    }


def run_validator(route_id: str, record: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(VALIDATOR),
            "--route-id",
            route_id,
            "--record",
            str(record),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=120,
    )
    parsed: dict[str, Any] | None = None
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        parsed = None
    return {
        "returncode": proc.returncode,
        "parsed": parsed,
        "output_tail": proc.stdout[-1200:],
    }


def forbidden_found(text: str) -> list[str]:
    lower = text.lower()
    return [snippet for snippet in FORBIDDEN_SNIPPETS if snippet.lower() in lower]


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def placeholder_count(obj: Any) -> int:
    text = json.dumps(obj, sort_keys=True)
    return len(re.findall(r"(\[[A-Z0-9_]+\]|<[^>\n]+>)", text))


def filled_record(template: dict[str, Any], route_id: str, *, min_subjects: int) -> dict[str, Any]:
    payload = deepcopy(template)
    payload.update(
        {
            "approved_access_recorded": True,
            "schema_probe_metadata_recorded": True,
            "target_free_manifest_preflight_passed": True,
            "formula_sha_record_preflight_passed": True,
            "schema_probe_record_reference": (
                f"synthetic_non_protected_{route_id}_schema_probe_record_hash"
            ),
            "target_free_manifest_reference": (
                f"synthetic_non_protected_{route_id}_target_free_manifest_hash"
            ),
            "formula_sha_record_reference": (
                f"synthetic_non_protected_{route_id}_formula_sha_record_hash"
            ),
            "formula_sha256": "1" * 64,
            "scoring_command": (
                f"uv run python scripts/score_{route_id}_zero_shot_after_approval.py "
                "--formula-record synthetic_non_protected_record"
            ),
            "created_at_utc": "2026-05-15T00:00:00+00:00",
            "git_sha": "0" * 40,
        }
    )
    for track in payload["tracks"]:
        if track["track_id"] in {"A", "B", "C"}:
            track["status"] = "scored"
            track["aggregate_metrics"] = {
                "n": min_subjects,
                "ccc": 0.1,
                "mae": 1.0,
            }
        if track["track_id"] == "D":
            track["status"] = "blocked"
            track["aggregate_metrics"] = {}
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def row_matches_spec(row: dict[str, Any], template: dict[str, Any], spec: Any) -> bool:
    return (
        row.get("id") == spec.route_id
        and row.get("name") == spec.name
        and tuple(row.get("required_grouping_keys") or ()) == spec.required_grouping_keys
        and tuple(row.get("required_target_columns") or ()) == spec.required_target_columns
        and tuple(row.get("required_sensor_modalities") or ())
        == spec.required_sensor_modalities
        and row.get("min_subjects") == spec.min_subjects
        and template.get("route_id") == spec.route_id
        and template.get("result_stage") == EXPECTED_RESULT_STAGE
    )


def expected_validator_command(route_id: str) -> str:
    return (
        "uv run python scripts/validate_external_zeroshot_result_record.py "
        f"--route-id {route_id} "
        "--record <completed_external_zeroshot_result_record_path_outside_git>"
    )


def post_score_reporting_workflow_valid(row: dict[str, Any]) -> bool:
    route_id = str(row.get("id"))
    return row.get("post_score_reporting_workflow_sequence") == [
        {
            "step_id": "validate_zeroshot_result_record",
            "command": expected_validator_command(route_id),
        },
        {
            "step_id": "audit_external_result_claim_labeling",
            "command": "uv run python audit_external_result_claim_labeling.py",
        },
        {
            "step_id": "audit_prompt_objective_evidence",
            "command": "uv run python audit_prompt_objective_evidence.py",
        },
        {
            "step_id": "verify_current_goal_state",
            "command": "uv run python verify_current_goal_state.py",
        },
    ]


def track_name_map(template: dict[str, Any]) -> dict[str, str]:
    tracks = template.get("tracks")
    if not isinstance(tracks, list):
        return {}
    names: dict[str, str] = {}
    for track in tracks:
        if isinstance(track, dict) and track.get("track_id"):
            names[str(track["track_id"])] = str(track.get("name", ""))
    return names


def ppmi_result_contract_present(template: dict[str, Any]) -> bool:
    contract = template.get("route_specific_formula_contract_acknowledged")
    if not isinstance(contract, dict):
        return False
    branch = contract.get("track_c_required_fixed_branch") or {}
    x4_policy = contract.get("x4_v3_gsp_compatibility_policy") or {}
    return (
        contract.get("blueprint_record_id") == "ppmi_verily_zeroshot_blueprint_20260515"
        and contract.get("blueprint_sha256") == PPMI_BLUEPRINT_SHA256
        and contract.get("formula_record_validator_gate")
        == "ppmi_route_specific_formula_contract"
        and contract.get("formula_record_preflight_must_have_passed") is True
        and contract.get("route_specific_track_names") == PPMI_ROUTE_SPECIFIC_TRACKS
        and track_name_map(template) == PPMI_ROUTE_SPECIFIC_TRACKS
        and set(contract.get("required_locked_formula_components") or ())
        >= PPMI_REQUIRED_LOCKED_FORMULA_COMPONENTS
        and branch.get("endpoint_scope") == "T3 only"
        and branch.get("model") == "sklearn.ensemble.GradientBoostingRegressor"
        and branch.get("selector") == "univariate_corr_top_K"
        and branch.get("K") == 250
        and branch.get("formula_sha256") == PPMI_K250_FORMULA_SHA256
        and x4_policy == PPMI_X4_V3_GSP_COMPATIBILITY_POLICY
        and contract.get("path_references_in_completed_result_record") is False
        and "external" in str(contract.get("aggregate_result_claim_scope", "")).lower()
    )


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# External Zero-Shot Result Templates Audit - 2026-05-15",
        "",
        "This audits the generic blank external zero-shot result templates and validator. It is not an approval, schema probe, completed result record, feature manifest, preregistration, model result, or completion marker.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Templates JSON: `{report['templates_json']}`",
        f"- Templates Markdown: `{report['templates_markdown']}`",
        f"- Template directory: `{report['template_dir']}`",
        f"- Validator: `{report['validator']}`",
        f"- Route count: `{report['route_count']}`",
        f"- Hard failures: `{len(report['hard_failures'])}`",
        "",
        "## Route Results",
        "",
        "| Route | Placeholder fails | Synthetic passes | Internal update fails | Protected fails | Low N fails | Local-path fails | PPMI contract fails |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for route_id, result in report["route_results"].items():
        lines.append(
            f"| `{route_id}` | `{result['placeholder_template_failed']}` | "
            f"`{result['synthetic_fill_passed']}` | `{result['internal_update_failed']}` | "
            f"`{result['protected_failed']}` | `{result['low_n_failed']}` | "
            f"`{result['local_path_failed']}` | "
            f"`{result['ppmi_contract_negative_failed']}` |"
        )
    lines.extend(["", "## Checks", ""])
    for row in report["checks"]:
        lines.append(f"- `{row['passed']}` {row['name']}")
    if report["hard_failures"]:
        lines.extend(["", "## Hard Failures", ""])
        for failure in report["hard_failures"]:
            lines.append(f"- {failure['name']}: {failure['evidence']}")
    else:
        lines.extend(["", "## Hard Failures", "", "- None."])
    lines.append("")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    writer = run_writer()
    templates_payload = load_json(TEMPLATES_JSON) if TEMPLATES_JSON.exists() else {}
    formula_sha_audit = load_json(FORMULA_SHA_AUDIT)
    md_text = TEMPLATES_MD.read_text(encoding="utf-8") if TEMPLATES_MD.exists() else ""
    specs = external_schema_probe_specs()
    routes = templates_payload.get("routes") or []
    route_ids = [row.get("id") for row in routes]
    route_by_id = {row.get("id"): row for row in routes}
    boundary = templates_payload.get("content_boundary") or {}
    combined_text = (
        json.dumps(templates_payload, sort_keys=True)
        + "\n"
        + md_text
        + "\n"
        + writer["stdout"]
    )
    found_forbidden = forbidden_found(combined_text)
    route_results: dict[str, dict[str, Any]] = {}

    for spec in specs:
        row = route_by_id.get(spec.route_id, {})
        template_path = ROOT / str(row.get("template_path", ""))
        template = load_json(template_path) if template_path.exists() else {}
        template_result = run_validator(spec.route_id, template_path) if template_path.exists() else {}
        template_parsed = template_result.get("parsed") or {}

        filled_path = SYNTH_DIR / f"{spec.route_id}_filled_zeroshot_result_record.json"
        safe_payload = filled_record(template, spec.route_id, min_subjects=spec.min_subjects)
        write_json(filled_path, safe_payload)
        filled_result = run_validator(spec.route_id, filled_path)
        filled_parsed = filled_result.get("parsed") or {}

        internal_path = SYNTH_DIR / f"{spec.route_id}_internal_update_result_record.json"
        internal_payload = deepcopy(safe_payload)
        internal_payload["internal_canonical_update_allowed"] = True
        internal_payload["claim_boundary"] = "Internal canonical update allowed."
        write_json(internal_path, internal_payload)
        internal_result = run_validator(spec.route_id, internal_path)
        internal_parsed = internal_result.get("parsed") or {}

        protected_path = SYNTH_DIR / f"{spec.route_id}_protected_result_record.json"
        protected_payload = deepcopy(safe_payload)
        protected_payload["subject_ids"] = ["SYN001"]
        protected_payload["target_values"] = [1, 2, 3]
        protected_payload["row_predictions"] = [{"sid": "SYN001", "y_pred": 1.0}]
        protected_payload["token"] = "synthetic-token-value-should-not-appear"
        write_json(protected_path, protected_payload)
        protected_result = run_validator(spec.route_id, protected_path)
        protected_parsed = protected_result.get("parsed") or {}

        low_n_path = SYNTH_DIR / f"{spec.route_id}_low_n_result_record.json"
        low_n_payload = deepcopy(safe_payload)
        low_n_payload["tracks"][0]["aggregate_metrics"]["n"] = spec.min_subjects - 1
        write_json(low_n_path, low_n_payload)
        low_n_result = run_validator(spec.route_id, low_n_path)
        low_n_parsed = low_n_result.get("parsed") or {}

        local_path = SYNTH_DIR / f"{spec.route_id}_local_path_result_record.json"
        local_path_payload = deepcopy(safe_payload)
        local_path_payload["formula_sha_record_reference"] = (
            "synthetic aggregate reference, but local scratch "
            f"/home/pi/{spec.route_id}_formula_sha_record.json should fail"
        )
        write_json(local_path, local_path_payload)
        local_path_result = run_validator(spec.route_id, local_path)
        local_path_parsed = local_path_result.get("parsed") or {}
        scratch_path = f"/home/pi/{spec.route_id}_formula_sha_record.json"
        scratch_filename = f"{spec.route_id}_formula_sha_record.json"

        ppmi_bad_contract_result: dict[str, Any] = {}
        ppmi_bad_contract_parsed: dict[str, Any] = {}
        ppmi_contract_negative_failed = True
        if spec.route_id == "ppmi_verily":
            ppmi_bad_contract_path = (
                SYNTH_DIR / f"{spec.route_id}_bad_result_contract_record.json"
            )
            ppmi_bad_contract_payload = deepcopy(safe_payload)
            for track in ppmi_bad_contract_payload["tracks"]:
                if track.get("track_id") == "C":
                    track["name"] = "ppmi_verily_only_grouped_sanity"
            write_json(ppmi_bad_contract_path, ppmi_bad_contract_payload)
            ppmi_bad_contract_result = run_validator(
                spec.route_id, ppmi_bad_contract_path
            )
            ppmi_bad_contract_parsed = ppmi_bad_contract_result.get("parsed") or {}
            ppmi_contract_negative_failed = (
                ppmi_bad_contract_result.get("returncode") != 0
                and "ppmi_route_specific_result_contract"
                in ppmi_bad_contract_parsed.get("hard_failures", [])
                and "track_metrics_are_aggregate_and_plausible"
                not in ppmi_bad_contract_parsed.get("hard_failures", [])
            )

        route_results[spec.route_id] = {
            "template_path": rel(template_path) if template_path.exists() else None,
            "placeholder_count": placeholder_count(template),
            "ppmi_result_contract_present": (
                spec.route_id != "ppmi_verily"
                or ppmi_result_contract_present(template)
            ),
            "placeholder_template_failed": template_result.get("returncode") != 0
            and "placeholders_replaced" in template_parsed.get("hard_failures", []),
            "synthetic_fill_passed": filled_result.get("returncode") == 0
            and filled_parsed.get("passed") is True
            and filled_parsed.get("decision")
            == "external_zero_shot_result_record_preflight_passed",
            "internal_update_failed": internal_result.get("returncode") != 0
            and "external_only_claim_boundary" in internal_parsed.get("hard_failures", [])
            and "boundary_flags_false" in internal_parsed.get("hard_failures", []),
            "protected_failed": protected_result.get("returncode") != 0
            and "protected_payload_keys_absent" in protected_parsed.get("hard_failures", []),
            "low_n_failed": low_n_result.get("returncode") != 0
            and "track_metrics_are_aggregate_and_plausible"
            in low_n_parsed.get("hard_failures", []),
            "local_path_failed": local_path_result.get("returncode") != 0
            and "forbidden_value_snippets_absent" in local_path_parsed.get("hard_failures", []),
            "ppmi_contract_negative_failed": ppmi_contract_negative_failed,
            "redaction_passed": (
                str(template_path) not in str(template_result.get("output_tail", ""))
                and template_path.name not in str(template_result.get("output_tail", ""))
                and str(filled_path) not in str(filled_result.get("output_tail", ""))
                and filled_path.name not in str(filled_result.get("output_tail", ""))
                and str(protected_path) not in str(protected_result.get("output_tail", ""))
                and protected_path.name not in str(protected_result.get("output_tail", ""))
                and str(local_path) not in str(local_path_result.get("output_tail", ""))
                and local_path.name not in str(local_path_result.get("output_tail", ""))
                and "synthetic-token-value-should-not-appear"
                not in str(protected_result.get("output_tail", ""))
                and scratch_path not in str(local_path_result.get("output_tail", ""))
                and scratch_filename not in str(local_path_result.get("output_tail", ""))
                and "bad_result_contract_record"
                not in str(ppmi_bad_contract_result.get("output_tail", ""))
            ),
            "template_hard_failures": template_parsed.get("hard_failures"),
            "synthetic_hard_failures": filled_parsed.get("hard_failures"),
            "internal_hard_failures": internal_parsed.get("hard_failures"),
            "protected_hard_failures": protected_parsed.get("hard_failures"),
            "low_n_hard_failures": low_n_parsed.get("hard_failures"),
            "local_path_hard_failures": local_path_parsed.get("hard_failures"),
            "ppmi_bad_contract_hard_failures": ppmi_bad_contract_parsed.get(
                "hard_failures"
            ),
        }

    checks = [
        check(
            "writer command succeeds and writes zero-shot result template outputs",
            writer["returncode"] == 0
            and (writer.get("parsed") or {}).get("json") == rel(TEMPLATES_JSON)
            and (writer.get("parsed") or {}).get("markdown") == rel(TEMPLATES_MD)
            and (writer.get("parsed") or {}).get("template_dir") == rel(TEMPLATE_DIR)
            and TEMPLATES_JSON.exists()
            and TEMPLATES_MD.exists()
            and TEMPLATE_DIR.exists(),
            {"returncode": writer["returncode"], "stdout": writer["stdout"][-800:]},
        ),
        check(
            "templates cover six schema-probe routes in contract order",
            templates_payload.get("decision")
            == "external_zeroshot_result_templates_ready"
            and templates_payload.get("route_count") == 6
            and route_ids == EXPECTED_ROUTE_IDS
            and route_ids == [spec.route_id for spec in specs]
            and templates_payload.get("goal_complete") is False,
            {"route_ids": route_ids, "spec_route_ids": [spec.route_id for spec in specs]},
        ),
        check(
            "template route rows mirror schema contracts",
            all(
                row_matches_spec(
                    route_by_id.get(spec.route_id, {}),
                    load_json(ROOT / str(route_by_id.get(spec.route_id, {}).get("template_path", ""))),
                    spec,
                )
                for spec in specs
            ),
            {"route_results": route_results},
        ),
        check(
            "blank result templates are post-score gated and not completed records",
            all(
                route_by_id.get(spec.route_id, {}).get("template", {}).get("result_stage")
                == EXPECTED_RESULT_STAGE
                and route_by_id.get(spec.route_id, {}).get("template", {}).get("status")
                == EXPECTED_TEMPLATE_STATUS
                and route_by_id.get(spec.route_id, {}).get("template", {}).get("external_only")
                is True
                and route_by_id.get(spec.route_id, {})
                .get("template", {})
                .get("internal_canonical_update_allowed")
                is False
                and all(
                    route_by_id.get(spec.route_id, {}).get("template", {}).get(key)
                    is False
                    for key in PRIOR_GATE_KEYS
                )
                and str(
                    route_by_id.get(spec.route_id, {})
                    .get("template", {})
                    .get("scoring_command", "")
                ).startswith("<FILL_")
                for spec in specs
            ),
            {
                "expected_result_stage": EXPECTED_RESULT_STAGE,
                "expected_template_status": EXPECTED_TEMPLATE_STATUS,
                "prior_gate_keys": PRIOR_GATE_KEYS,
            },
        ),
        check(
            "every route exposes an ordered post-score reporting workflow sequence",
            all(post_score_reporting_workflow_valid(row) for row in routes)
            and "Post-score reporting workflow sequence:" in md_text
            and "1. `validate_zeroshot_result_record`" in md_text
            and "2. `audit_external_result_claim_labeling`" in md_text
            and "3. `audit_prompt_objective_evidence`" in md_text
            and "4. `verify_current_goal_state`" in md_text,
            {
                "expected_step_ids": EXPECTED_POST_SCORE_REPORTING_WORKFLOW_STEP_IDS,
                "workflow_by_route": {
                    row.get("id"): [
                        step.get("step_id")
                        for step in row.get(
                            "post_score_reporting_workflow_sequence", []
                        )
                    ]
                    for row in routes
                },
                "ppmi_workflow": route_by_id.get("ppmi_verily", {}).get(
                    "post_score_reporting_workflow_sequence"
                ),
            },
        ),
        check(
            "all templates are unfinished placeholders and synthetic fills pass",
            all(
                result["placeholder_count"] > 0
                and result["placeholder_template_failed"]
                and result["synthetic_fill_passed"]
                and result["internal_update_failed"]
                and result["protected_failed"]
                and result["low_n_failed"]
                and result["local_path_failed"]
                and result["ppmi_result_contract_present"]
                and result["ppmi_contract_negative_failed"]
                and result["redaction_passed"]
                for result in route_results.values()
            ),
            {"route_results": route_results},
        ),
        check(
            "PPMI result template carries route-specific track and formula-gate contract",
            route_results.get("ppmi_verily", {}).get("ppmi_result_contract_present")
            is True
            and route_results.get("ppmi_verily", {}).get("ppmi_contract_negative_failed")
            is True
            and "ppmi_route_specific_formula_contract" in combined_text
            and "weargait_trained_wrist_topofractal_zeroshot" in combined_text
            and "ppmi_only_subject_grouped_sanity" in combined_text
            and "separate fixed K=250 sklearn-GB branch for T3 only" in combined_text,
            {"ppmi_route_result": route_results.get("ppmi_verily")},
        ),
        check(
            "template boundary flags are false and external-only",
            all(
                route_by_id.get(spec.route_id, {}).get("template", {}).get(key) is False
                for spec in specs
                for key in FALSE_BOUNDARY_KEYS
            )
            and all(
                route_by_id.get(spec.route_id, {}).get("template", {}).get("external_only")
                is True
                for spec in specs
            ),
            {"false_boundary_keys": sorted(FALSE_BOUNDARY_KEYS), "route_ids": route_ids},
        ),
        check(
            "formula-SHA template audit remains ready",
            formula_sha_audit.get("passed") is True
            and formula_sha_audit.get("decision") == "external_formula_sha_templates_ready"
            and formula_sha_audit.get("route_count") == 6,
            {
                "decision": formula_sha_audit.get("decision"),
                "hard_failures": formula_sha_audit.get("hard_failures"),
            },
        ),
        check(
            "content boundary blocks completed/protected artifacts",
            templates_payload.get("not_a_submission_record") is True
            and templates_payload.get("not_access_approval") is True
            and templates_payload.get("not_a_schema_probe_artifact") is True
            and templates_payload.get("not_a_feature_manifest_artifact") is True
            and templates_payload.get("not_a_preregistration") is True
            and templates_payload.get("not_a_model_result") is True
            and boundary.get("completed_result_records_included") is False
            and boundary.get("protected_data_included") is False
            and boundary.get("approval_evidence_included") is False
            and boundary.get("schema_probe_artifacts_included") is False
            and boundary.get("feature_manifest_artifacts_included") is False
            and boundary.get("preregistration_artifacts_included") is False
            and boundary.get("credentials_or_tokens_included") is False
            and boundary.get("target_values_included") is False
            and boundary.get("row_level_data_included") is False
            and boundary.get("feature_matrix_included") is False
            and boundary.get("row_predictions_included") is False
            and boundary.get("model_outputs_included") is False
            and boundary.get("local_paths_included") is False
            and boundary.get("path_like_values_allowed") is False
            and boundary.get("completed_file_references_in_values_allowed") is False
            and boundary.get("subject_visit_identifier_value_dumps_allowed") is False,
            {"content_boundary": boundary},
        ),
        check(
            "markdown boundary documents stricter value-scrubbing policy",
            "path-like values inside otherwise allowed fields" in md_text
            and "completed-file extensions" in md_text
            and "download/file-path strings" in md_text
            and "subject/visit identifier value dumps" in md_text
            and "Validators fail closed" in md_text,
            {"boundary_excerpt": md_text.split("## Boundary", 1)[-1][:1200]},
        ),
        check(
            "template output does not expose private artifacts",
            not found_forbidden,
            {"forbidden_snippets_found": found_forbidden},
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_external_zeroshot_result_templates.py",
        "writer": "scripts/write_external_zeroshot_result_templates.py",
        "validator": "scripts/validate_external_zeroshot_result_record.py",
        "templates_json": rel(TEMPLATES_JSON),
        "templates_markdown": rel(TEMPLATES_MD),
        "template_dir": rel(TEMPLATE_DIR),
        "source_schema_contract": "pd_imu.datasets.external_schema_probe_specs",
        "passed": not hard_failures,
        "decision": (
            "external_zeroshot_result_templates_ready"
            if not hard_failures
            else "external_zeroshot_result_templates_failed"
        ),
        "route_count": len(routes),
        "route_ids": route_ids,
        "route_results": route_results,
        "post_score_reporting_workflow_by_route": {
            row.get("id"): row.get("post_score_reporting_workflow_sequence", [])
            for row in routes
        },
        "post_score_reporting_workflow_step_ids_by_route": {
            row.get("id"): [
                step.get("step_id")
                for step in row.get("post_score_reporting_workflow_sequence", [])
            ]
            for row in routes
        },
        "checks": checks,
        "hard_failures": hard_failures,
        "not_a_submission_record": True,
        "not_access_approval": True,
        "not_a_schema_probe_artifact": True,
        "not_a_feature_manifest_artifact": True,
        "not_a_preregistration": True,
        "not_a_model_result": True,
        "protected_data_included": False,
        "credentials_or_tokens_included": False,
        "goal_complete": False,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(report)
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "decision": report["decision"],
                "hard_failure_count": len(hard_failures),
                "route_count": report["route_count"],
            },
            indent=2,
        )
    )
    if hard_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
