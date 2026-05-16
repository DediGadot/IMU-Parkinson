#!/usr/bin/env python3
"""Audit generic all-route formula-SHA templates and preflight validator."""

from __future__ import annotations

import hashlib
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
SCRIPT = ROOT / "scripts" / "write_external_formula_sha_templates.py"
VALIDATOR = ROOT / "scripts" / "validate_external_formula_sha_record.py"
TEMPLATES_JSON = RESULTS / "external_formula_sha_templates_20260515.json"
TEMPLATES_MD = RESULTS / "external_formula_sha_templates_20260515.md"
TEMPLATE_DIR = RESULTS / "external_formula_sha_templates_20260515"
SYNTH_DIR = RESULTS / "external_formula_sha_templates_synthetic"
ZEROSHOT_BLUEPRINT_AUDIT = RESULTS / "external_zeroshot_blueprint_handoff_audit_20260515.json"
OUT_JSON = RESULTS / "external_formula_sha_templates_audit_20260515.json"
OUT_MD = RESULTS / "external_formula_sha_templates_audit_20260515.md"

EXPECTED_ROUTE_IDS = [
    "ppmi_verily",
    "ppp_pd_vme",
    "watchpd",
    "cns_portugal_lobo",
    "hssayeni_mjff",
    "icicle_gait",
]
EXPECTED_ANALYSIS_ORDER = [
    "schema_probe_metadata_record",
    "target_free_manifest_preflight",
    "formula_sha256_after_manifest_before_extraction_or_scoring",
    "zero_shot_external_validation",
]
EXPECTED_POST_FORMULA_WORKFLOW_STEP_IDS = [
    "validate_formula_sha_record",
    "validate_zeroshot_result_record",
]
RETIRED_ANALYSIS_STEPS = [
    "formula_sha256_after_schema_before_extraction_or_scoring",
]
FALSE_BOUNDARY_KEYS = {
    "external_labels_used_to_design_formula",
    "target_values_used_to_design_formula",
    "protected_data_included",
    "credentials_or_tokens_included",
    "raw_rows_or_samples_included",
    "feature_matrix_included",
    "target_values_included",
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


def canonical_sha(obj: Any) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


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


def filled_record(template: dict[str, Any], route_id: str) -> dict[str, Any]:
    payload = deepcopy(template)
    payload.update(
        {
            "schema_probe_metadata_recorded": True,
            "target_free_manifest_preflight_passed": True,
            "schema_probe_record_reference": (
                f"synthetic_non_protected_{route_id}_schema_probe_record_hash"
            ),
            "target_free_manifest_reference": (
                f"synthetic_non_protected_{route_id}_target_free_manifest_hash"
            ),
            "created_at_utc": "2026-05-15T00:00:00+00:00",
            "git_sha": "0" * 40,
        }
    )
    payload["formula_sha256"] = canonical_sha(payload["formula_json"])
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def row_matches_spec(row: dict[str, Any], template: dict[str, Any], spec: Any) -> bool:
    formula = template.get("formula_json", {})
    return (
        row.get("id") == spec.route_id
        and row.get("name") == spec.name
        and tuple(row.get("required_grouping_keys") or ()) == spec.required_grouping_keys
        and tuple(row.get("required_target_columns") or ()) == spec.required_target_columns
        and tuple(row.get("required_sensor_modalities") or ())
        == spec.required_sensor_modalities
        and row.get("min_subjects") == spec.min_subjects
        and template.get("route_id") == spec.route_id
        and formula.get("route_id") == spec.route_id
        and tuple(formula.get("required_grouping_keys") or ()) == spec.required_grouping_keys
        and tuple(formula.get("required_target_columns") or ()) == spec.required_target_columns
        and tuple(formula.get("required_sensor_modalities") or ())
        == spec.required_sensor_modalities
        and template.get("analysis_order_acknowledged") == EXPECTED_ANALYSIS_ORDER
    )


def track_map(formula: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tracks = formula.get("tracks")
    if not isinstance(tracks, list):
        return {}
    mapped: dict[str, dict[str, Any]] = {}
    for track in tracks:
        if isinstance(track, dict) and track.get("track_id"):
            mapped[str(track["track_id"])] = track
    return mapped


def ppmi_formula_contract_present(template: dict[str, Any]) -> bool:
    formula = template.get("formula_json")
    if not isinstance(formula, dict):
        return False
    contract = formula.get("route_specific_blueprint_contract")
    if not isinstance(contract, dict):
        return False
    tracks = track_map(formula)
    track_names = {
        track_id: track.get("name")
        for track_id, track in tracks.items()
    }
    track_a_contract = tracks.get("A", {}).get("branch_contract") or {}
    track_b_contract = tracks.get("B", {}).get("branch_contract") or {}
    track_c_branch = tracks.get("C", {}).get("fixed_branch") or {}
    track_c_contract = contract.get("track_c_required_fixed_branch") or {}
    branch_policy = contract.get("global_branch_policy") or {}
    x4_policy = contract.get("x4_v3_gsp_compatibility_policy") or {}
    track_a_x4_policy = track_a_contract.get("x4_v3_gsp_compatibility_policy") or {}
    return (
        contract.get("blueprint_record_id") == "ppmi_verily_zeroshot_blueprint_20260515"
        and contract.get("blueprint_audit_record_id")
        == "ppmi_verily_zeroshot_blueprint_audit_20260515"
        and contract.get("blueprint_sha256") == PPMI_BLUEPRINT_SHA256
        and contract.get("must_use_for_exact_track_definitions") is True
        and set(contract.get("required_locked_formula_components") or ())
        >= PPMI_REQUIRED_LOCKED_FORMULA_COMPONENTS
        and contract.get("route_specific_track_names") == PPMI_ROUTE_SPECIFIC_TRACKS
        and track_names == PPMI_ROUTE_SPECIFIC_TRACKS
        and track_a_contract.get("branch_type") == "small_fixed_topofractal"
        and track_b_contract.get("branch_type") == "canonical_comparator"
        and tracks.get("C", {}).get("endpoint_scope") == "T3 only"
        and track_c_branch.get("model") == "sklearn.ensemble.GradientBoostingRegressor"
        and track_c_branch.get("selector") == "univariate_corr_top_K"
        and track_c_branch.get("K") == 250
        and track_c_branch.get("formula_sha256") == PPMI_K250_FORMULA_SHA256
        and track_c_contract.get("model") == "sklearn.ensemble.GradientBoostingRegressor"
        and track_c_contract.get("selector") == "univariate_corr_top_K"
        and track_c_contract.get("K") == 250
        and track_c_contract.get("formula_sha256") == PPMI_K250_FORMULA_SHA256
        and branch_policy.get("omnibus_feature_expansion") is False
        and branch_policy.get("cross_branch_adaptive_stacking_before_zero_shot_results")
        is False
        and x4_policy == PPMI_X4_V3_GSP_COMPATIBILITY_POLICY
        and track_a_x4_policy == PPMI_X4_V3_GSP_COMPATIBILITY_POLICY
    )


def expected_validator_command(route_id: str) -> str:
    return (
        "uv run python scripts/validate_external_formula_sha_record.py "
        f"--route-id {route_id} "
        "--record <completed_formula_sha_record_path_outside_git>"
    )


def expected_result_validator_command(route_id: str) -> str:
    return (
        "uv run python scripts/validate_external_zeroshot_result_record.py "
        f"--route-id {route_id} "
        "--record <completed_external_zeroshot_result_record_path_outside_git>"
    )


def post_formula_workflow_valid(row: dict[str, Any]) -> bool:
    route_id = str(row.get("id"))
    return row.get("post_formula_workflow_sequence") == [
        {
            "step_id": "validate_formula_sha_record",
            "command": expected_validator_command(route_id),
        },
        {
            "step_id": "validate_zeroshot_result_record",
            "command": expected_result_validator_command(route_id),
        },
    ]


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# External Formula-SHA Templates Audit - 2026-05-15",
        "",
        "This audits the generic blank formula-SHA templates and validator. It is not an approval, schema probe, completed formula record, feature manifest, preregistration, model result, or completion marker.",
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
        "| Route | Placeholder fails | Synthetic passes | Bad SHA fails | Label fail | Protected fail | Local-path fail | PPMI contract fail |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for route_id, result in report["route_results"].items():
        lines.append(
            f"| `{route_id}` | `{result['placeholder_template_failed']}` | "
            f"`{result['synthetic_fill_passed']}` | `{result['bad_sha_failed']}` | "
            f"`{result['label_use_failed']}` | `{result['protected_failed']}` | "
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
    zeroshot_blueprint_audit = load_json(ZEROSHOT_BLUEPRINT_AUDIT)
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

        filled_path = SYNTH_DIR / f"{spec.route_id}_filled_formula_sha_record.json"
        safe_payload = filled_record(template, spec.route_id)
        write_json(filled_path, safe_payload)
        filled_result = run_validator(spec.route_id, filled_path)
        filled_parsed = filled_result.get("parsed") or {}

        bad_sha_path = SYNTH_DIR / f"{spec.route_id}_bad_sha_formula_record.json"
        bad_sha_payload = deepcopy(safe_payload)
        bad_sha_payload["formula_sha256"] = "0" * 64
        write_json(bad_sha_path, bad_sha_payload)
        bad_sha_result = run_validator(spec.route_id, bad_sha_path)
        bad_sha_parsed = bad_sha_result.get("parsed") or {}

        label_path = SYNTH_DIR / f"{spec.route_id}_label_formula_record.json"
        label_payload = deepcopy(safe_payload)
        label_payload["external_labels_used_to_design_formula"] = True
        label_payload["target_values_used_to_design_formula"] = True
        label_payload["target_values_included"] = True
        write_json(label_path, label_payload)
        label_result = run_validator(spec.route_id, label_path)
        label_parsed = label_result.get("parsed") or {}

        protected_path = SYNTH_DIR / f"{spec.route_id}_protected_formula_record.json"
        protected_payload = deepcopy(safe_payload)
        protected_payload["subject_ids"] = ["SYN001"]
        protected_payload["raw_samples"] = {"acc_x": [0.0, 1.0]}
        protected_payload["token"] = "synthetic-token-value-should-not-appear"
        write_json(protected_path, protected_payload)
        protected_result = run_validator(spec.route_id, protected_path)
        protected_parsed = protected_result.get("parsed") or {}

        local_path = SYNTH_DIR / f"{spec.route_id}_local_path_formula_record.json"
        local_path_payload = deepcopy(safe_payload)
        local_path_payload["target_free_manifest_reference"] = (
            "synthetic aggregate reference, but local scratch "
            f"/home/pi/{spec.route_id}_target_free_manifest.json should fail"
        )
        write_json(local_path, local_path_payload)
        local_path_result = run_validator(spec.route_id, local_path)
        local_path_parsed = local_path_result.get("parsed") or {}
        scratch_path = f"/home/pi/{spec.route_id}_target_free_manifest.json"
        scratch_filename = f"{spec.route_id}_target_free_manifest.json"

        ppmi_bad_contract_result: dict[str, Any] = {}
        ppmi_bad_contract_parsed: dict[str, Any] = {}
        ppmi_contract_negative_failed = True
        if spec.route_id == "ppmi_verily":
            ppmi_bad_contract_path = (
                SYNTH_DIR / f"{spec.route_id}_bad_route_contract_formula_record.json"
            )
            ppmi_bad_contract_payload = deepcopy(safe_payload)
            for track in ppmi_bad_contract_payload["formula_json"]["tracks"]:
                if track.get("track_id") == "C":
                    track["fixed_branch"]["K"] = 300
            ppmi_bad_contract_payload["formula_json"][
                "route_specific_blueprint_contract"
            ]["track_c_required_fixed_branch"]["K"] = 300
            ppmi_bad_contract_payload["formula_sha256"] = canonical_sha(
                ppmi_bad_contract_payload["formula_json"]
            )
            write_json(ppmi_bad_contract_path, ppmi_bad_contract_payload)
            ppmi_bad_contract_result = run_validator(
                spec.route_id, ppmi_bad_contract_path
            )
            ppmi_bad_contract_parsed = ppmi_bad_contract_result.get("parsed") or {}
            ppmi_contract_negative_failed = (
                ppmi_bad_contract_result.get("returncode") != 0
                and "ppmi_route_specific_formula_contract"
                in ppmi_bad_contract_parsed.get("hard_failures", [])
                and "formula_sha_matches"
                not in ppmi_bad_contract_parsed.get("hard_failures", [])
            )

        route_results[spec.route_id] = {
            "template_path": rel(template_path) if template_path.exists() else None,
            "placeholder_count": placeholder_count(template),
            "ppmi_formula_contract_present": (
                spec.route_id != "ppmi_verily"
                or ppmi_formula_contract_present(template)
            ),
            "placeholder_template_failed": template_result.get("returncode") != 0
            and "placeholders_replaced" in template_parsed.get("hard_failures", []),
            "synthetic_fill_passed": filled_result.get("returncode") == 0
            and filled_parsed.get("passed") is True
            and filled_parsed.get("decision")
            == "external_formula_sha_record_preflight_passed",
            "bad_sha_failed": bad_sha_result.get("returncode") != 0
            and "formula_sha_matches" in bad_sha_parsed.get("hard_failures", []),
            "label_use_failed": label_result.get("returncode") != 0
            and "labels_not_used_to_design_formula" in label_parsed.get("hard_failures", [])
            and "boundary_flags_false" in label_parsed.get("hard_failures", []),
            "protected_failed": protected_result.get("returncode") != 0
            and "protected_payload_keys_absent" in protected_parsed.get("hard_failures", []),
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
                and "bad_route_contract_formula_record"
                not in str(ppmi_bad_contract_result.get("output_tail", ""))
            ),
            "template_hard_failures": template_parsed.get("hard_failures"),
            "synthetic_hard_failures": filled_parsed.get("hard_failures"),
            "bad_sha_hard_failures": bad_sha_parsed.get("hard_failures"),
            "label_hard_failures": label_parsed.get("hard_failures"),
            "protected_hard_failures": protected_parsed.get("hard_failures"),
            "local_path_hard_failures": local_path_parsed.get("hard_failures"),
            "ppmi_bad_contract_hard_failures": ppmi_bad_contract_parsed.get(
                "hard_failures"
            ),
        }

    checks = [
        check(
            "writer command succeeds and writes formula-SHA template outputs",
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
            templates_payload.get("decision") == "external_formula_sha_templates_ready"
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
            "templates require post-manifest formula-SHA analysis order",
            all(
                route_by_id.get(spec.route_id, {})
                .get("template", {})
                .get("analysis_order_acknowledged")
                == EXPECTED_ANALYSIS_ORDER
                for spec in specs
            )
            and not any(step in combined_text for step in RETIRED_ANALYSIS_STEPS),
            {
                "expected_analysis_order": EXPECTED_ANALYSIS_ORDER,
                "retired_analysis_steps": RETIRED_ANALYSIS_STEPS,
            },
        ),
        check(
            "every route exposes an ordered post-formula workflow sequence",
            all(post_formula_workflow_valid(row) for row in routes)
            and "Post-formula workflow sequence:" in md_text
            and "1. `validate_formula_sha_record`" in md_text
            and "2. `validate_zeroshot_result_record`" in md_text,
            {
                "expected_step_ids": EXPECTED_POST_FORMULA_WORKFLOW_STEP_IDS,
                "workflow_by_route": {
                    row.get("id"): [
                        step.get("step_id")
                        for step in row.get("post_formula_workflow_sequence", [])
                    ]
                    for row in routes
                },
                "ppmi_workflow": route_by_id.get("ppmi_verily", {}).get(
                    "post_formula_workflow_sequence"
                ),
            },
        ),
        check(
            "all templates are unfinished placeholders and synthetic fills pass",
            all(
                result["placeholder_count"] > 0
                and result["placeholder_template_failed"]
                and result["synthetic_fill_passed"]
                and result["bad_sha_failed"]
                and result["label_use_failed"]
                and result["protected_failed"]
                and result["local_path_failed"]
                and result["ppmi_formula_contract_present"]
                and result["ppmi_contract_negative_failed"]
                and result["redaction_passed"]
                for result in route_results.values()
            ),
            {"route_results": route_results},
        ),
        check(
            "PPMI formula template carries the route-specific TopoFractal/K250 branch contract",
            route_results.get("ppmi_verily", {}).get("ppmi_formula_contract_present")
            is True
            and route_results.get("ppmi_verily", {}).get("ppmi_contract_negative_failed")
            is True
            and "small fixed TopoFractal PH/MFDFA branch" in combined_text
            and "separate fixed K=250 sklearn-GB branch for T3 only" in combined_text
            and "weargait_trained_wrist_topofractal_zeroshot" in combined_text
            and "ppmi_only_subject_grouped_sanity" in combined_text
            and "sklearn.ensemble.GradientBoostingRegressor" in combined_text,
            {"ppmi_route_result": route_results.get("ppmi_verily")},
        ),
        check(
            "template boundary flags are false and pre-scoring",
            all(
                route_by_id.get(spec.route_id, {}).get("template", {}).get(key) is False
                for spec in specs
                for key in FALSE_BOUNDARY_KEYS
            )
            and all(
                route_by_id.get(spec.route_id, {}).get("template", {}).get("record_stage")
                == "post_schema_pre_extraction_or_scoring_formula_sha"
                for spec in specs
            ),
            {"false_boundary_keys": sorted(FALSE_BOUNDARY_KEYS), "route_ids": route_ids},
        ),
        check(
            "zero-shot blueprint handoff remains ready",
            zeroshot_blueprint_audit.get("passed") is True
            and zeroshot_blueprint_audit.get("decision")
            == "external_zeroshot_blueprint_handoff_ready"
            and zeroshot_blueprint_audit.get("route_count") == 6,
            {
                "decision": zeroshot_blueprint_audit.get("decision"),
                "hard_failures": zeroshot_blueprint_audit.get("hard_failures"),
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
            and boundary.get("completed_formula_records_included") is False
            and boundary.get("protected_data_included") is False
            and boundary.get("approval_evidence_included") is False
            and boundary.get("schema_probe_artifacts_included") is False
            and boundary.get("feature_manifest_artifacts_included") is False
            and boundary.get("preregistration_artifacts_included") is False
            and boundary.get("credentials_or_tokens_included") is False
            and boundary.get("target_values_included") is False
            and boundary.get("row_level_data_included") is False
            and boundary.get("feature_matrix_included") is False
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
        "script": "audit_external_formula_sha_templates.py",
        "writer": "scripts/write_external_formula_sha_templates.py",
        "validator": "scripts/validate_external_formula_sha_record.py",
        "templates_json": rel(TEMPLATES_JSON),
        "templates_markdown": rel(TEMPLATES_MD),
        "template_dir": rel(TEMPLATE_DIR),
        "source_schema_contract": "pd_imu.datasets.external_schema_probe_specs",
        "passed": not hard_failures,
        "decision": (
            "external_formula_sha_templates_ready"
            if not hard_failures
            else "external_formula_sha_templates_failed"
        ),
        "route_count": len(routes),
        "route_ids": route_ids,
        "route_results": route_results,
        "post_formula_workflow_step_ids_by_route": {
            row.get("id"): [
                step.get("step_id")
                for step in row.get("post_formula_workflow_sequence", [])
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
