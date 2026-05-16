#!/usr/bin/env python3
"""Verify preregistration artifact content validation before experiment runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pd_imu.core import ArtifactLedger
from pd_imu.experiments import (
    ExperimentArtifact,
    ExperimentExecutionGate,
    ExperimentSpec,
    PreregistrationArtifactEvidence,
    PreregistrationRecord,
)
from pd_imu.pipelines import (
    ArtifactSpec,
    DatasetSpec,
    FeatureBlockSpec,
    GateSpec,
    PipelineSpec,
    TargetSpec,
    ValidationSpec,
)


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
PREREG_PATH = "results/preregistration_artifact_contract_demo_20260510.json"
OUT_JSON = RESULTS / "preregistration_artifact_gate_audit_20260510.json"
OUT_MD = RESULTS / "preregistration_artifact_gate_audit_20260510.md"


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def experiment() -> ExperimentSpec:
    pipeline = PipelineSpec(
        name="demo_internal_t3",
        version="2026-05-10",
        objective="Internal demo pipeline for preregistration artifact validation",
        dataset=DatasetSpec(name="weargait", cohort="pd_only", grouping_keys=("sid",), min_subjects=20),
        target=TargetSpec(name="updrs3", kind="mds_updrs_part3_total", valid_range=(0.0, 132.0)),
        validation=ValidationSpec(strategy="grouped_5fold", group_key="sid", n_splits=5, seeds=(42, 1337, 7)),
        gate=GateSpec(min_delta=0.025, max_seed_std=0.02),
        artifacts=ArtifactSpec(results_prefix="demo_internal_t3"),
        features=(FeatureBlockSpec(name="manifested_features", source="results/demo_features.csv"),),
    )
    return ExperimentSpec(
        name=pipeline.name,
        pipeline=pipeline,
        command=("uv", "run", "python", "run_demo_internal_t3.py", "--run"),
        preregistration=PreregistrationRecord.from_pipeline(
            pipeline,
            created_at_utc="2026-05-10T00:00:00Z",
            git_sha="abcdef1234567890abcdef1234567890abcdef12",
        ),
        artifacts=(
            ExperimentArtifact("preregistration", PREREG_PATH),
            ExperimentArtifact("oof_predictions", "results/demo_internal_t3_oof.csv"),
            ExperimentArtifact("manifest", "results/demo_internal_t3_features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "results/demo_internal_t3_rows.csv"),
        ),
    )


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    spec = experiment()
    prereg_payload = spec.preregistration.to_dict()
    (ROOT / PREREG_PATH).write_text(json.dumps(prereg_payload, indent=2, sort_keys=True), encoding="utf-8")

    evidence = PreregistrationArtifactEvidence.from_file(PREREG_PATH, root=ROOT)
    stale_evidence = PreregistrationArtifactEvidence(
        path=PREREG_PATH,
        payload={**prereg_payload, "formula_sha256": "0" * 64},
    )
    malformed_evidence = PreregistrationArtifactEvidence(
        path=PREREG_PATH,
        payload={
            **prereg_payload,
            "formula_sha256": "not-a-sha",
            "git_sha": "unknown",
            "notes": "not-a-list",
        },
    )
    hidden_rows_evidence = PreregistrationArtifactEvidence(
        path=PREREG_PATH,
        payload={**prereg_payload, "rows": [{"sid": "S1", "updrs3": 42}]},
    )
    secret_evidence = PreregistrationArtifactEvidence(
        path=PREREG_PATH,
        payload={**prereg_payload, "metadata": {"access_token": "do-not-store"}},
    )
    non_object_evidence = PreregistrationArtifactEvidence(path=PREREG_PATH, payload=[])
    undeclared_path_evidence = PreregistrationArtifactEvidence(
        path="results/undeclared_preregistration.json",
        payload=prereg_payload,
    )
    loader_tmp = RESULTS / "_preregistration_loader_tmp"
    loader_tmp.mkdir(exist_ok=True)
    bad_loader_json = loader_tmp / "bad_preregistration.json"
    bad_loader_json.write_text("{not-json", encoding="utf-8")
    missing_loader_evidence = PreregistrationArtifactEvidence.from_file(
        "missing_preregistration.json",
        root=loader_tmp,
    )
    bad_loader_evidence = PreregistrationArtifactEvidence.from_file(
        "bad_preregistration.json",
        root=loader_tmp,
    )
    bad_loader_json.unlink(missing_ok=True)
    loader_tmp.rmdir()
    run_without_content_errors = ExperimentExecutionGate(
        stage="run",
        experiment=spec,
        artifact_ledger=ArtifactLedger.from_paths((PREREG_PATH,), root=ROOT),
    ).validation_errors()
    run_with_content_gate = ExperimentExecutionGate(
        stage="run",
        experiment=spec,
        artifact_ledger=ArtifactLedger.from_paths((PREREG_PATH,), root=ROOT),
        preregistration_evidence=evidence,
    )

    checks = [
        check(
            "matching preregistration file validates against experiment spec",
            evidence.validation_errors_for(spec) == [],
            {"errors": evidence.validation_errors_for(spec), "path": PREREG_PATH},
        ),
        check(
            "stale formula hash is rejected",
            "preregistration.formula_sha256 does not match experiment" in stale_evidence.validation_errors_for(spec),
            {"errors": stale_evidence.validation_errors_for(spec)},
        ),
        check(
            "malformed preregistration fields fail closed",
            all(
                expected in malformed_evidence.validation_errors_for(spec)
                for expected in [
                    "preregistration.formula_sha256 must be 64 hex characters",
                    "preregistration.git_sha must be 40 hex characters when provided",
                    "preregistration.notes must be a list",
                ]
            )
            and non_object_evidence.validation_errors_for(spec) == ["preregistration payload must be an object"],
            {
                "malformed_errors": malformed_evidence.validation_errors_for(spec),
                "non_object_errors": non_object_evidence.validation_errors_for(spec),
            },
        ),
        check(
            "preregistration artifact loader errors fail closed",
            all(
                expected in errors
                for errors, expected in [
                    (
                        missing_loader_evidence.validation_errors_for(spec),
                        "preregistration artifact source is missing: missing_preregistration.json",
                    ),
                    (
                        bad_loader_evidence.validation_errors_for(spec),
                        "preregistration artifact source is not valid JSON: bad_preregistration.json",
                    ),
                ]
            ),
            {
                "missing_errors": missing_loader_evidence.validation_errors_for(spec),
                "bad_json_errors": bad_loader_evidence.validation_errors_for(spec),
            },
        ),
        check(
            "row-like preregistration payload is rejected",
            "preregistration artifact contains prohibited protected-content key: preregistration.rows"
            in hidden_rows_evidence.validation_errors_for(spec),
            {"errors": hidden_rows_evidence.validation_errors_for(spec)},
        ),
        check(
            "credential-like preregistration payload is rejected",
            "preregistration artifact contains prohibited protected-content key: preregistration.metadata.access_token"
            in secret_evidence.validation_errors_for(spec),
            {"errors": secret_evidence.validation_errors_for(spec)},
        ),
        check(
            "undeclared preregistration path is rejected",
            "preregistration artifact path is not declared by experiment"
            in undeclared_path_evidence.validation_errors_for(spec),
            {"errors": undeclared_path_evidence.validation_errors_for(spec)},
        ),
        check(
            "run stage requires preregistration content evidence",
            "run stage requires preregistration content evidence" in run_without_content_errors
            and run_with_content_gate.can_execute(),
            {
                "without_content_errors": run_without_content_errors,
                "with_content_errors": run_with_content_gate.validation_errors(),
            },
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_preregistration_artifact_gate.py",
        "not_a_model_result": True,
        "goal_complete": False,
        "passed": not hard_failures,
        "decision": "preregistration_artifact_gate_passed"
        if not hard_failures
        else "preregistration_artifact_gate_failed",
        "checks": checks,
        "hard_failures": hard_failures,
        "claim": "Run-stage execution now requires preregistration content evidence, not only an observed preregistration path. Preregistration artifacts also fail closed on malformed scalar fields, missing or invalid source JSON, and row-like or credential-like payload keys.",
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# Preregistration Artifact Gate Audit - 2026-05-10",
        "",
        "This verifies content validation for preregistration artifacts before future runs. It is not a model result.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Hard failures: `{len(hard_failures)}`",
        "",
        "## Checks",
        "",
    ]
    for row in checks:
        lines.append(f"- `{row['passed']}` {row['name']}")
    lines.extend(
        [
            "",
            "## Claim",
            "",
            report["claim"],
            "",
            f"Machine-readable report: `{OUT_JSON.relative_to(ROOT).as_posix()}`",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "decision": report["decision"],
                "hard_failures": len(hard_failures),
            },
            indent=2,
            sort_keys=True,
        )
    )
    if hard_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
