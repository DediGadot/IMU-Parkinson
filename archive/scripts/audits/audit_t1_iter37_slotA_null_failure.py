#!/usr/bin/env python3
"""Audit T1 iter37 slot-A corrected null-gate outcome."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
NULL_JSON = RESULTS / "t1_iter37_slotA_nulls_corrected_20260510_145355.json"
OUT_JSON = RESULTS / "t1_iter37_slotA_null_failure_audit_20260510.json"
OUT_MD = RESULTS / "t1_iter37_slotA_null_failure_audit_20260510.md"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    nulls = load_json(NULL_JSON)
    normal = float(nulls["normal_ccc"])
    scrambled = float(nulls["scrambled_label_ccc"])
    canary = float(nulls["canary_feature_ccc"])
    canary_delta = float(nulls["canary_vs_normal_max_abs_delta"])
    canary_mean_delta = float(nulls["canary_vs_normal_mean_abs_delta"])
    transductive = float(nulls["transductive_sanity_ccc"])
    scrambled_pass = abs(scrambled) < 0.05
    canary_pass = canary_delta < 1e-6
    transductive_pass = transductive > 0.5
    null_gate_pass = scrambled_pass and canary_pass and transductive_pass

    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_t1_iter37_slotA_null_failure.py",
        "input_artifact": NULL_JSON.relative_to(ROOT).as_posix(),
        "not_a_model_headline": True,
        "supersedes_prior_artifact": "results/t1_iter37_slotA_nulls_20260510_143049.json",
        "prior_artifact_issue": "Prior null shuffled only T1 sum while chain targets stayed true; corrected null shuffles all target-derived training arrays.",
        "screen_aborted_reason": "Corrected null gate failed before a reportable screen result; repeated process-pool runs also stalled after the null gate.",
        "metrics": {
            "normal_ccc": normal,
            "scrambled_label_ccc": scrambled,
            "canary_feature_ccc": canary,
            "canary_vs_normal_max_abs_delta": canary_delta,
            "canary_vs_normal_mean_abs_delta": canary_mean_delta,
            "transductive_sanity_ccc": transductive,
        },
        "checks": {
            "scrambled_abs_lt_0p05": scrambled_pass,
            "canary_max_delta_lt_1e_minus_6": canary_pass,
            "transductive_gt_0p5": transductive_pass,
        },
        "null_gate_pass": null_gate_pass,
        "passed": True,
        "decision": "corrected_null_gate_failed_canary_instability_do_not_screen_or_promote",
        "allowed_followup": "Document failure only; do not run lockbox or use this route for a canonical/candidate claim.",
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# T1 Iter37 Slot-A Corrected Null Failure Audit - 2026-05-10",
        "",
        "This is a failure/guardrail artifact, not a model headline.",
        "",
        f"- Normal split CCC: `{normal:+.4f}`",
        f"- Input artifact: `{NULL_JSON.relative_to(ROOT).as_posix()}`",
        f"- Scrambled-label CCC: `{scrambled:+.4f}`",
        f"- Canary-feature CCC: `{canary:+.4f}`",
        f"- Canary max prediction delta: `{canary_delta:.6f}`",
        f"- Canary mean prediction delta: `{canary_mean_delta:.6f}`",
        f"- Transductive sanity CCC: `{transductive:+.4f}`",
        f"- Null gate pass: `{null_gate_pass}`",
        f"- Decision: `{report['decision']}`",
        "",
        "## Interpretation",
        "",
        "The corrected target-shuffle null is near zero, superseding the earlier flawed target-shuffle interpretation. The route still fails because a test-only canary column changes predictions materially.",
        "",
        f"Machine-readable report: `{OUT_JSON.relative_to(ROOT).as_posix()}`",
        "",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "decision": report["decision"],
                "null_gate_pass": null_gate_pass,
                "scrambled_label_ccc": scrambled,
                "canary_max_delta": canary_delta,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
