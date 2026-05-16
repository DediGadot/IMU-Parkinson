#!/usr/bin/env python3
"""Verify the typed registry for current internal WearGait-PD result claims."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pd_imu.reporting import ClaimSpec, CurrentResultClaim, current_weargait_reporting_gate, current_weargait_result_claims


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "current_truth_registry_audit_20260510.json"
OUT_MD = RESULTS / "current_truth_registry_audit_20260510.md"


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    demo_source = RESULTS / "current_truth_registry_demo_source.json"
    demo_prereg = RESULTS / "current_truth_registry_demo_prereg.json"
    demo_source.write_text(json.dumps({"metrics": {"ccc": 0.1, "n": 1}}, indent=2), encoding="utf-8")
    demo_prereg.write_text(json.dumps({"demo": True}, indent=2), encoding="utf-8")
    claims = current_weargait_result_claims()
    gate = current_weargait_reporting_gate(root=ROOT)
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")

    names = tuple(entry.claim.name for entry in claims)
    labels = {entry.claim.name: entry.claim.label for entry in claims}
    validation_errors = {entry.claim.name: entry.validation_errors(root=ROOT) for entry in claims}
    metric_errors = {
        entry.claim.name: entry.metric_evidence(root=ROOT).validation_errors_for(entry.claim)
        for entry in claims
    }
    artifact_paths = tuple(dict.fromkeys(path for entry in claims for path in entry.artifact_paths()))
    malformed_entry = CurrentResultClaim(
        claim=ClaimSpec(
            name="malformed_registry_entry",
            label="canonical",
            source_artifact=demo_source.relative_to(ROOT).as_posix(),
            metric="ccc",
            value=0.1,
            n_subjects=1,
        ),
        metric_value_path=42,
        n_subjects_path=(),
        command=("uv", "", "python"),
        preregistration_artifact=demo_prereg.relative_to(ROOT).as_posix(),
        required_artifacts=(demo_source.relative_to(ROOT).as_posix(), 123, demo_prereg.relative_to(ROOT).as_posix()),
        notes=("ok", None),
    )
    malformed_errors = malformed_entry.validation_errors(root=ROOT)
    malformed_claim_entry = CurrentResultClaim(
        claim=object(),
        metric_value_path="metrics.ccc",
        n_subjects_path="metrics.n",
        command=("uv", "run", "python", "demo.py"),
        preregistration_artifact=demo_prereg.relative_to(ROOT).as_posix(),
        required_artifacts=(demo_prereg.relative_to(ROOT).as_posix(),),
    )
    malformed_claim_errors = malformed_claim_entry.validation_errors(root=ROOT)
    malformed_claim_metric_error = ""
    try:
        malformed_claim_entry.metric_evidence(root=ROOT)
    except ValueError as exc:
        malformed_claim_metric_error = str(exc)
    malformed_claim_scalar_entry = CurrentResultClaim(
        claim=ClaimSpec(
            name=123,
            label=1,
            source_artifact=[],
            metric=(),
            value="0.1",
            n_subjects="1",
            updates_internal_canonical="yes",
        ),
        metric_value_path="metrics.ccc",
        n_subjects_path="metrics.n",
        command=("uv", "run", "python", "demo.py"),
    )
    malformed_claim_scalar_errors = malformed_claim_scalar_entry.validation_errors(root=ROOT)
    malformed_root_entry = CurrentResultClaim(
        claim=ClaimSpec(
            name="malformed_root_registry_entry",
            label="canonical",
            source_artifact=demo_source.relative_to(ROOT).as_posix(),
            metric="ccc",
            value=0.1,
            n_subjects=1,
        ),
        metric_value_path="metrics.ccc",
        n_subjects_path="metrics.n",
        command=("uv", "run", "python", "demo.py"),
    )
    malformed_root_errors = malformed_root_entry.validation_errors(root=object())

    checks = [
        check(
            "registry has the expected current internal truth entries",
            names
            == (
                "t1_iter12_canonical_floor",
                "t1_iter34_strongest_candidate",
                "t3_iter47_corrected_validrange",
                "t3_iter47_loso_transportability",
            ),
            {"names": names},
        ),
        check(
            "registry preserves canonical vs candidate labels",
            labels
            == {
                "t1_iter12_canonical_floor": "canonical",
                "t1_iter34_strongest_candidate": "candidate",
                "t3_iter47_corrected_validrange": "canonical",
                "t3_iter47_loso_transportability": "canonical",
            },
            {"labels": labels},
        ),
        check(
            "registry artifact paths exist and claim specs validate",
            all(not errors for errors in validation_errors.values()),
            {"validation_errors": validation_errors, "artifact_paths": artifact_paths},
        ),
        check(
            "registered metric evidence matches source JSON artifacts",
            all(not errors for errors in metric_errors.values()) and gate.can_emit(),
            {"metric_errors": metric_errors, "gate_errors": gate.validation_errors()},
        ),
        check(
            "registry rejects malformed command/path/artifact metadata",
            all(
                expected in malformed_errors
                for expected in [
                    "malformed_registry_entry: command entries must be non-empty strings",
                    "malformed_registry_entry: metric_value_path is required",
                    "malformed_registry_entry: n_subjects_path is required",
                    "malformed_registry_entry: required_artifacts entries must be non-empty strings",
                    "malformed_registry_entry: notes entries must be strings",
                    f"malformed_registry_entry: duplicate artifact reference: {demo_source.relative_to(ROOT).as_posix()}",
                    f"malformed_registry_entry: duplicate artifact reference: {demo_prereg.relative_to(ROOT).as_posix()}",
                ]
            ),
            {"errors": malformed_errors},
        ),
        check(
            "registry rejects malformed nested claim objects",
            "claim must be a ClaimSpec" in malformed_claim_errors
            and f"<invalid claim>: duplicate artifact reference: {demo_prereg.relative_to(ROOT).as_posix()}"
            in malformed_claim_errors
            and malformed_claim_entry.artifact_paths() == (demo_prereg.relative_to(ROOT).as_posix(),)
            and malformed_claim_metric_error == "claim must be a ClaimSpec"
            and all(
                expected in malformed_claim_scalar_errors
                for expected in [
                    "name is required",
                    "label 1 is not allowed",
                    "source_artifact is required",
                    "metric must be a non-empty string when set",
                    "value must be numeric when set",
                    "n_subjects must be an integer when set",
                    "updates_internal_canonical must be a boolean",
                ]
            )
            and malformed_claim_scalar_entry.artifact_paths() == (),
            {
                "malformed_claim_errors": malformed_claim_errors,
                "malformed_claim_metric_error": malformed_claim_metric_error,
                "malformed_claim_scalar_errors": malformed_claim_scalar_errors,
            },
        ),
        check(
            "registry artifact root/path observation errors fail closed",
            "malformed_root_registry_entry: root must be a string or Path" in malformed_root_errors,
            {"errors": malformed_root_errors},
        ),
        check(
            "registry values match the current CLAUDE.md truth table",
            all(
                snippet in claude
                for snippet in [
                    "T1 canonical floor",
                    "0.6550",
                    "T1 corrected candidate",
                    "0.7170",
                    "T3 iter47 corrected target",
                    "0.3784",
                    "T3 LOSO transportability",
                    "0.150",
                ]
            ),
            {"source": "CLAUDE.md"},
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_current_truth_registry.py",
        "not_a_model_result": True,
        "goal_complete": False,
        "passed": not hard_failures,
        "decision": "current_truth_registry_passed" if not hard_failures else "current_truth_registry_failed",
        "checks": checks,
        "hard_failures": hard_failures,
        "claim": (
            "Current internal WearGait-PD result claims now have a reusable typed registry "
            "that binds canonical/candidate labels, source artifacts, commands, preregistration "
            "artifacts, JSON metric paths, and validated supporting-artifact metadata before "
            "reporting gates consume them. Malformed nested claim objects fail closed before "
            "registry helpers dereference claim fields. Malformed registry roots or artifact "
            "observation failures also fail closed as validation errors."
        ),
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# Current Truth Registry Audit - 2026-05-10",
        "",
        "This verifies the typed current-result registry. It is not a model result.",
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
