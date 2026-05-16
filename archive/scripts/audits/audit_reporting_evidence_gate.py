#!/usr/bin/env python3
"""Verify reporting surfaces are gated by observed claim source artifacts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pd_imu.core import ArtifactLedger
from pd_imu.reporting import (
    ClaimMetricEvidence,
    ClaimSpec,
    ReportingEvidenceGate,
    ReportingSurfaceSpec,
    current_weargait_result_claims,
)


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "reporting_evidence_gate_audit_20260510.json"
OUT_MD = RESULTS / "reporting_evidence_gate_audit_20260510.md"


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def observed_existing(paths: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(path for path in paths if (ROOT / path).exists())


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    internal_entries = current_weargait_result_claims()
    internal_claims = tuple(entry.claim for entry in internal_entries)
    canonical = next(claim for claim in internal_claims if claim.name == "t3_iter47_corrected_validrange")
    candidate = next(claim for claim in internal_claims if claim.name == "t1_iter34_strongest_candidate")
    external = ClaimSpec(
        name="cops_external",
        label="external_transport",
        source_artifact="results/iter49_cops_zeroshot.json",
        metric="ccc",
        value=0.2412,
        n_subjects=62,
        caveat="External transportability evidence only; does not update internal WearGait-PD canonicals.",
    )
    surface = ReportingSurfaceSpec(
        name="current_paper_claims",
        path="CURRENT_PAPER.html",
        claims=(*internal_claims, external),
        required_snippets=("strongest candidate", "not canonical", "External transportability evidence only"),
    )
    observed_paths = observed_existing(tuple(claim.source_artifact for claim in surface.claims))
    metric_evidence = (
        *(entry.metric_evidence(root=ROOT) for entry in internal_entries),
        ClaimMetricEvidence.from_json_file(
            claim_name="cops_external",
            source_artifact=external.source_artifact,
            metric_value_path="metrics.off_primary.track_b_right_clinical_plus_wrist.ccc",
            n_subjects_path="metrics.off_primary.track_b_right_clinical_plus_wrist.n",
            root=ROOT,
        ),
    )
    hashed_ledger = ArtifactLedger.from_paths(observed_paths, root=ROOT, hash_existing=True)
    stale_metric_evidence = (
        *(evidence for evidence in metric_evidence if evidence.claim_name != candidate.name),
        ClaimMetricEvidence(
            claim_name=candidate.name,
            source_artifact=candidate.source_artifact,
            payload={"ccc": 0.1, "n_subjects": 93},
            metric_value_path="ccc",
            n_subjects_path="n_subjects",
        ),
    )
    complete_text = (
        "T1 iter34 is strongest candidate, not canonical. "
        "External transportability evidence only; internal WearGait-PD canonicals are unchanged."
    )
    missing_artifact_gate = ReportingEvidenceGate(
        surface=surface,
        observed_artifact_paths=(),
        artifact_ledger=ArtifactLedger.from_paths(
            tuple(path for path in observed_paths if path != external.source_artifact),
            root=ROOT,
            hash_existing=True,
        ),
        rendered_text=complete_text,
        claim_metric_evidence=metric_evidence,
    )
    complete_gate = ReportingEvidenceGate(
        surface=surface,
        observed_artifact_paths=(),
        artifact_ledger=hashed_ledger,
        rendered_text=complete_text,
        claim_metric_evidence=metric_evidence,
    )
    missing_text_gate = ReportingEvidenceGate(
        surface=surface,
        observed_artifact_paths=(),
        artifact_ledger=hashed_ledger,
        rendered_text="T1 iter34 is strongest candidate.",
        claim_metric_evidence=metric_evidence,
    )
    stale_metric_gate = ReportingEvidenceGate(
        surface=surface,
        observed_artifact_paths=(),
        artifact_ledger=hashed_ledger,
        rendered_text=complete_text,
        claim_metric_evidence=stale_metric_evidence,
    )
    nonhex_metric_hash_gate = ReportingEvidenceGate(
        surface=surface,
        observed_artifact_paths=(),
        artifact_ledger=None,
        rendered_text=complete_text,
        claim_metric_evidence=(
            *(evidence for evidence in metric_evidence if evidence.claim_name != candidate.name),
            ClaimMetricEvidence(
                claim_name=candidate.name,
                source_artifact=candidate.source_artifact,
                payload={"ccc": candidate.value, "n_subjects": candidate.n_subjects},
                metric_value_path="ccc",
                n_subjects_path="n_subjects",
                sha256="z" * 64,
            ),
        ),
    )
    malformed_metric_path_gate = ReportingEvidenceGate(
        surface=surface,
        observed_artifact_paths=(),
        artifact_ledger=None,
        rendered_text=complete_text,
        claim_metric_evidence=(
            *(evidence for evidence in metric_evidence if evidence.claim_name != candidate.name),
            ClaimMetricEvidence(
                claim_name=candidate.name,
                source_artifact=candidate.source_artifact,
                payload={"ccc": candidate.value, "n_subjects": candidate.n_subjects},
                metric_value_path="ccc[bad]",
                n_subjects_path="n_subjects",
            ),
        ),
    )
    empty_segment_metric_path_gate = ReportingEvidenceGate(
        surface=surface,
        observed_artifact_paths=(),
        artifact_ledger=None,
        rendered_text=complete_text,
        claim_metric_evidence=(
            *(evidence for evidence in metric_evidence if evidence.claim_name != candidate.name),
            ClaimMetricEvidence(
                claim_name=candidate.name,
                source_artifact=candidate.source_artifact,
                payload={"ccc": candidate.value, "n_subjects": candidate.n_subjects},
                metric_value_path="ccc..value",
                n_subjects_path="n_subjects",
            ),
        ),
    )
    protected_metric_payload_gate = ReportingEvidenceGate(
        surface=surface,
        observed_artifact_paths=(),
        artifact_ledger=None,
        rendered_text=complete_text,
        claim_metric_evidence=(
            *(evidence for evidence in metric_evidence if evidence.claim_name != candidate.name),
            ClaimMetricEvidence(
                claim_name=candidate.name,
                source_artifact=candidate.source_artifact,
                payload={
                    "ccc": candidate.value,
                    "n_subjects": candidate.n_subjects,
                    "rows": [{"sid": "S001", "y_true": 8.0, "y_pred": 8.5}],
                    "metadata": {"access_token": "do-not-store"},
                },
                metric_value_path="ccc",
                n_subjects_path="n_subjects",
            ),
        ),
    )
    malformed_metric_payload_gate = ReportingEvidenceGate(
        surface=surface,
        observed_artifact_paths=(),
        artifact_ledger=None,
        rendered_text=complete_text,
        claim_metric_evidence=(
            *(evidence for evidence in metric_evidence if evidence.claim_name != candidate.name),
            ClaimMetricEvidence(
                claim_name=candidate.name,
                source_artifact=candidate.source_artifact,
                payload=[],
                metric_value_path="ccc",
                n_subjects_path="n_subjects",
            ),
        ),
    )
    nonnumeric_metric_payload_gate = ReportingEvidenceGate(
        surface=surface,
        observed_artifact_paths=(),
        artifact_ledger=None,
        rendered_text=complete_text,
        claim_metric_evidence=(
            *(evidence for evidence in metric_evidence if evidence.claim_name != candidate.name),
            ClaimMetricEvidence(
                claim_name=candidate.name,
                source_artifact=candidate.source_artifact,
                payload={"ccc": {"value": candidate.value}, "n_subjects": "ninety-three"},
                metric_value_path="ccc",
                n_subjects_path="n_subjects",
            ),
        ),
    )
    loader_tmp = RESULTS / "_reporting_evidence_loader_tmp"
    loader_tmp.mkdir(exist_ok=True)
    bad_loader_json = loader_tmp / "bad.json"
    bad_loader_json.write_text("{not-json", encoding="utf-8")
    loader_missing_claim = ClaimSpec(
        name="loader_missing",
        label="canonical",
        source_artifact="missing.json",
        metric="ccc",
        value=0.3784,
        n_subjects=95,
    )
    loader_bad_claim = ClaimSpec(
        name="loader_bad_json",
        label="canonical",
        source_artifact="bad.json",
        metric="ccc",
        value=0.3784,
        n_subjects=95,
    )
    loader_missing_gate = ReportingEvidenceGate(
        surface=ReportingSurfaceSpec(
            name="loader_missing_surface",
            path="CURRENT_PAPER.html",
            claims=(loader_missing_claim,),
        ),
        observed_artifact_paths=("missing.json",),
        artifact_ledger=None,
        rendered_text=complete_text,
        claim_metric_evidence=(
            ClaimMetricEvidence.from_json_file(
                claim_name=loader_missing_claim.name,
                source_artifact=loader_missing_claim.source_artifact,
                metric_value_path="metrics.ccc",
                n_subjects_path="metrics.n",
                root=loader_tmp,
            ),
        ),
    )
    loader_bad_json_gate = ReportingEvidenceGate(
        surface=ReportingSurfaceSpec(
            name="loader_bad_json_surface",
            path="CURRENT_PAPER.html",
            claims=(loader_bad_claim,),
        ),
        observed_artifact_paths=("bad.json",),
        artifact_ledger=None,
        rendered_text=complete_text,
        claim_metric_evidence=(
            ClaimMetricEvidence.from_json_file(
                claim_name=loader_bad_claim.name,
                source_artifact=loader_bad_claim.source_artifact,
                metric_value_path="metrics.ccc",
                n_subjects_path="metrics.n",
                root=loader_tmp,
            ),
        ),
    )
    bad_loader_json.unlink(missing_ok=True)
    loader_tmp.rmdir()
    duplicate_surface = ReportingSurfaceSpec(
        name="duplicate_claim_surface",
        path="CURRENT_PAPER.html",
        claims=(
            canonical,
            ClaimSpec(
                name=canonical.name,
                label="canonical",
                source_artifact=canonical.source_artifact,
                metric=canonical.metric,
                value=canonical.value,
                n_subjects=canonical.n_subjects,
            ),
        ),
    )
    duplicate_metric_evidence_gate = ReportingEvidenceGate(
        surface=surface,
        observed_artifact_paths=(),
        artifact_ledger=hashed_ledger,
        rendered_text=complete_text,
        claim_metric_evidence=(metric_evidence[0], *metric_evidence),
    )
    stray_metric_evidence_gate = ReportingEvidenceGate(
        surface=surface,
        observed_artifact_paths=(),
        artifact_ledger=hashed_ledger,
        rendered_text=complete_text,
        claim_metric_evidence=(
            *metric_evidence,
            ClaimMetricEvidence(
                claim_name="not_in_surface",
                source_artifact="results/not_in_surface.json",
                payload={"metrics": {"ccc": 0.0, "n": 1}},
                metric_value_path="metrics.ccc",
                n_subjects_path="metrics.n",
            ),
        ),
    )
    malformed_gate = ReportingEvidenceGate(
        surface=object(),
        observed_artifact_paths=object(),
        artifact_ledger=object(),
        rendered_text=object(),
        claim_metric_evidence=object(),
    )
    malformed_gate_errors = malformed_gate.validation_errors()
    malformed_claim = ClaimSpec(
        name=123,
        label=1,
        source_artifact=[],
        metric=(),
        value="0.1",
        n_subjects="95",
        caveat=42,
        updates_internal_canonical="yes",
    )
    malformed_surface = ReportingSurfaceSpec(
        name=123,
        path=None,
        claims=(object(), malformed_claim),
        required_snippets=("required", 4),
    )
    malformed_surface_errors = malformed_surface.validation_errors(text=object())
    malformed_evidence_gate = ReportingEvidenceGate(
        surface=ReportingSurfaceSpec(name="paper", path="CURRENT_PAPER.html", claims=(candidate,)),
        observed_artifact_paths=(candidate.source_artifact, 3),
        artifact_ledger=ArtifactLedger.from_paths(candidate.source_artifact, root=ROOT),
        rendered_text=complete_text,
        claim_metric_evidence=(
            object(),
            ClaimMetricEvidence(
                claim_name=(),
                source_artifact=candidate.source_artifact,
                payload={"ccc": candidate.value, "n_subjects": candidate.n_subjects},
                metric_value_path="ccc",
                n_subjects_path="n_subjects",
            ),
        ),
    )
    malformed_evidence_errors = malformed_evidence_gate.validation_errors()

    checks = [
        check(
            "source artifacts used in audit exist locally",
            set(observed_paths) == {claim.source_artifact for claim in surface.claims},
            {"observed_paths": observed_paths},
        ),
        check(
            "internal reporting claims come from current truth registry",
            tuple(claim.name for claim in internal_claims)
            == tuple(entry.claim.name for entry in current_weargait_result_claims())
            and all(evidence.claim_name in {claim.name for claim in internal_claims} for evidence in metric_evidence[:-1]),
            {"internal_claims": tuple(claim.name for claim in internal_claims)},
        ),
        check(
            "complete reporting evidence gate can emit",
            complete_gate.can_emit(),
            {"errors": complete_gate.validation_errors()},
        ),
        check(
            "missing source artifact blocks emission",
            not missing_artifact_gate.can_emit()
            and f"missing claim source artifact: {external.source_artifact}" in missing_artifact_gate.validation_errors(),
            {"errors": missing_artifact_gate.validation_errors()},
        ),
        check(
            "missing required framing text blocks emission",
            not missing_text_gate.can_emit()
            and "missing required snippet: not canonical" in missing_text_gate.validation_errors(),
            {"errors": missing_text_gate.validation_errors()},
        ),
        check(
            "stale metric evidence blocks emission",
            not stale_metric_gate.can_emit()
            and any(
                f"{candidate.name}: metric value mismatch" in error
                for error in stale_metric_gate.validation_errors()
            ),
            {"errors": stale_metric_gate.validation_errors()},
        ),
        check(
            "hashed source artifacts require matching metric evidence hashes",
            any(
                f"{candidate.name}: claim metric evidence sha256 is required when artifact ledger is hashed" in error
                for error in stale_metric_gate.validation_errors()
            ),
            {"errors": stale_metric_gate.validation_errors()},
        ),
        check(
            "claim metric evidence hashes must be hex",
            any(
                f"{candidate.name}: claim metric evidence sha256 must be 64 hex characters" in error
                for error in nonhex_metric_hash_gate.validation_errors()
            ),
            {"errors": nonhex_metric_hash_gate.validation_errors()},
        ),
        check(
            "claim metric evidence JSON path syntax errors fail closed",
            any(
                f"{candidate.name}: metric value path error: malformed index [bad] in 'ccc[bad]'" in error
                for error in malformed_metric_path_gate.validation_errors()
            ),
            {"errors": malformed_metric_path_gate.validation_errors()},
        ),
        check(
            "claim metric evidence JSON paths reject empty segments",
            any(
                f"{candidate.name}: metric value path error: malformed path 'ccc..value'" in error
                for error in empty_segment_metric_path_gate.validation_errors()
            ),
            {"errors": empty_segment_metric_path_gate.validation_errors()},
        ),
        check(
            "claim metric evidence malformed/protected payloads fail closed",
            all(
                expected in errors
                for errors, expected in [
                    (
                        protected_metric_payload_gate.validation_errors(),
                        f"{candidate.name}: claim metric evidence contains prohibited protected-content key: "
                        "claim_metric_evidence.rows",
                    ),
                    (
                        protected_metric_payload_gate.validation_errors(),
                        f"{candidate.name}: claim metric evidence contains prohibited protected-content key: "
                        "claim_metric_evidence.metadata.access_token",
                    ),
                    (
                        malformed_metric_payload_gate.validation_errors(),
                        f"{candidate.name}: claim metric evidence payload must be an object",
                    ),
                    (
                        nonnumeric_metric_payload_gate.validation_errors(),
                        f"{candidate.name}: metric value at ccc must be numeric",
                    ),
                    (
                        nonnumeric_metric_payload_gate.validation_errors(),
                        f"{candidate.name}: n_subjects at n_subjects must be numeric",
                    ),
                ]
            ),
            {
                "protected_errors": protected_metric_payload_gate.validation_errors(),
                "malformed_errors": malformed_metric_payload_gate.validation_errors(),
                "nonnumeric_errors": nonnumeric_metric_payload_gate.validation_errors(),
            },
        ),
        check(
            "claim metric evidence loader errors fail closed",
            not loader_missing_gate.can_emit()
            and not loader_bad_json_gate.can_emit()
            and any(
                "loader_missing: claim metric evidence source artifact is missing: missing.json" in error
                for error in loader_missing_gate.validation_errors()
            )
            and any(
                "loader_bad_json: claim metric evidence source artifact is not valid JSON: bad.json" in error
                for error in loader_bad_json_gate.validation_errors()
            ),
            {
                "missing_errors": loader_missing_gate.validation_errors(),
                "bad_json_errors": loader_bad_json_gate.validation_errors(),
            },
        ),
        check(
            "duplicate claim names block ambiguous metric evidence",
            f"duplicate claim name: {canonical.name}" in duplicate_surface.validation_errors(),
            {"errors": duplicate_surface.validation_errors()},
        ),
        check(
            "duplicate metric evidence names block silent overwrite",
            f"duplicate claim metric evidence: {metric_evidence[0].claim_name}"
            in duplicate_metric_evidence_gate.validation_errors(),
            {"errors": duplicate_metric_evidence_gate.validation_errors()},
        ),
        check(
            "metric evidence for unknown claims blocks emission",
            "unexpected claim metric evidence: not_in_surface" in stray_metric_evidence_gate.validation_errors(),
            {"errors": stray_metric_evidence_gate.validation_errors()},
        ),
        check(
            "malformed reporting gate objects fail closed",
            not malformed_gate.can_emit()
            and "surface must be a ReportingSurfaceSpec" in malformed_gate_errors
            and "observed_artifact_paths must be a tuple or list" in malformed_gate_errors
            and "artifact_ledger must be an ArtifactLedger" in malformed_gate_errors
            and "claim_metric_evidence must be a tuple or list" in malformed_gate_errors
            and malformed_gate.observed_artifacts() == set()
            and malformed_gate.missing_source_artifacts() == ()
            and "claims entries must be ClaimSpec" in malformed_surface_errors
            and "rendered text must be a string when set" in malformed_surface_errors
            and "123: updates_internal_canonical must be a boolean" in malformed_surface_errors
            and "observed_artifact_paths entries must be non-empty strings" in malformed_evidence_errors
            and "artifact_ledger: paths must be a tuple or list" in malformed_evidence_errors
            and "claim_metric_evidence entries must be ClaimMetricEvidence" in malformed_evidence_errors
            and "claim_metric_evidence entries must have non-empty claim_name" in malformed_evidence_errors,
            {
                "malformed_gate_errors": malformed_gate_errors,
                "malformed_surface_errors": malformed_surface_errors,
                "malformed_evidence_errors": malformed_evidence_errors,
            },
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_reporting_evidence_gate.py",
        "not_a_model_result": True,
        "goal_complete": False,
        "passed": not hard_failures,
        "decision": "reporting_evidence_gate_passed" if not hard_failures else "reporting_evidence_gate_failed",
        "checks": checks,
        "hard_failures": hard_failures,
        "claim": "Reporting surfaces now have a reusable evidence gate: a surface can emit claims only when claim labels/framing validate, current internal truth claims come from the typed registry, claim names and metric-evidence names are unique, every metric-evidence entry belongs to a surface claim, every claim source artifact is present, metric-evidence hashes are true hex SHA-256 values, malformed metric-evidence JSON paths fail closed, including empty path segments, row-like or credential-like claim metric payload keys fail closed, malformed claim metric payloads fail closed, claim metric evidence loader errors fail closed, malformed reporting surface/gate objects fail closed, hashed source artifacts match metric-evidence hashes, and metric/value/N claims match parsed source-artifact evidence.",
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# Reporting Evidence Gate Audit - 2026-05-10",
        "",
        "This verifies claim-source artifact gating for reporting surfaces. It is not a model result.",
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
