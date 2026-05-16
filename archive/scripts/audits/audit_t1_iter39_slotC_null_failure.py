#!/usr/bin/env python3
"""Audit T1 iter39 slot-C corrected null-gate outcome."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
NULL_JSON = RESULTS / "t1_iter39_slotC_nulls_20260510_144649.json"
OUT_JSON = RESULTS / "t1_iter39_slotC_null_failure_audit_20260510.json"
OUT_MD = RESULTS / "t1_iter39_slotC_null_failure_audit_20260510.md"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    nulls = load_json(NULL_JSON)
    scrambled = float(nulls["scrambled_label_ccc"])
    canary_delta = float(nulls["canary_vs_normal_max_abs_delta"])
    canary_mean_delta = float(nulls["canary_vs_normal_mean_abs_delta"])
    transductive = float(nulls["transductive_sanity_ccc"])
    normal_ccc = float(nulls["normal_ccc"])
    scrambled_pass = abs(scrambled) < 0.05
    canary_pass = canary_delta < 1e-6
    transductive_pass = transductive > 0.5
    null_gate_pass = scrambled_pass and canary_pass and transductive_pass

    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_t1_iter39_slotC_null_failure.py",
        "input_artifact": NULL_JSON.relative_to(ROOT).as_posix(),
        "not_a_model_headline": True,
        "metrics": {
            "normal_ccc": normal_ccc,
            "scrambled_label_ccc": scrambled,
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
        "decision": "corrected_null_gate_failed_do_not_screen_or_promote",
        "allowed_followup": "Document failure only; do not run screen, lockbox, or candidate/canonical claim.",
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# T1 Iter39 Slot-C Null Failure Audit - 2026-05-10",
        "",
        "This is a failure/guardrail artifact, not a model headline.",
        "",
        f"- Input artifact: `{NULL_JSON.relative_to(ROOT).as_posix()}`",
        f"- Normal split CCC: `{normal_ccc:+.4f}`",
        f"- Scrambled-label CCC: `{scrambled:+.4f}`",
        f"- Canary max prediction delta: `{canary_delta:.6f}`",
        f"- Canary mean prediction delta: `{canary_mean_delta:.6f}`",
        f"- Transductive sanity CCC: `{transductive:+.4f}`",
        f"- Null gate pass: `{null_gate_pass}`",
        f"- Decision: `{report['decision']}`",
        "",
        "## Interpretation",
        "",
        "The corrected target-shuffle null is outside the near-zero threshold, and adding a test-only canary column changes predictions materially. Slot C is closed before 5-fold screening.",
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
