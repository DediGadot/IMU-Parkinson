"""Reporting and claim-label contracts for new WearGait-PD outputs."""

from pd_imu.reporting.claims import (
    CanonicalClaimUpdateGate,
    ClaimMetricEvidence,
    ClaimSpec,
    ReportingEvidenceGate,
    ReportingSurfaceSpec,
)
from pd_imu.reporting.current_truth import (
    CurrentResultClaim,
    current_weargait_reporting_gate,
    current_weargait_result_claims,
)

__all__ = [
    "CanonicalClaimUpdateGate",
    "ClaimMetricEvidence",
    "ClaimSpec",
    "CurrentResultClaim",
    "ReportingEvidenceGate",
    "ReportingSurfaceSpec",
    "current_weargait_reporting_gate",
    "current_weargait_result_claims",
]
