#!/usr/bin/env python3
"""Audit the 2026-05-10 T1 glass-ceiling architecture push closure."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "t1_ceiling_push_closure_audit_20260510.json"
OUT_MD = RESULTS / "t1_ceiling_push_closure_audit_20260510.md"


SLOTS = {
    "A": {
        "name": "phase_locked_post_k500_items_9_12",
        "screen": RESULTS / "screen_t1_iter37_slotA_20260510_142637.json",
        "prereg": RESULTS / "preregistration_t1_iter37_phaselocked_postk500_20260510_140536.json",
        "expected_delta": -0.0020839336799750217,
        "expected_frac_above_zero": 0.1716,
    },
    "B": {
        "name": "fog_balance_post_k500_items_11_13",
        "screen": RESULTS / "screen_t1_iter38_slotB_20260510_143503.json",
        "prereg": RESULTS / "preregistration_t1_iter38_fog_balance_postk500_20260510_143243.json",
        "expected_delta": -0.00020745621855078333,
        "expected_frac_above_zero": 0.498,
    },
    "C": {
        "name": "per_item_averaged_k500_selection",
        "screen": RESULTS / "screen_t1_iter39_slotC_20260510_144445.json",
        "prereg": RESULTS / "preregistration_t1_iter39_peritem_kselect_20260510_144156.json",
        "expected_delta": -0.020157674304133105,
        "expected_frac_above_zero": 0.056,
    },
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def close(a: float, b: float, tol: float = 5e-4) -> bool:
    return abs(float(a) - float(b)) <= tol


def main() -> None:
    findings = (ROOT / "findings.md").read_text(encoding="utf-8")
    rows: list[dict[str, Any]] = []
    hard_failures: list[dict[str, Any]] = []

    for slot_id, spec in SLOTS.items():
        screen = load_json(spec["screen"])
        prereg = load_json(spec["prereg"])
        boot = screen["bootstrap_paired_delta"]
        checks = {
            "screen_exists": spec["screen"].exists(),
            "prereg_exists": spec["prereg"].exists(),
            "n_subjects_92": screen.get("n_subjects") == 92,
            "gate_failed": screen.get("screen_gate_pass") is False,
            "delta_matches_expected": close(screen.get("delta_mean"), spec["expected_delta"]),
            "frac_above_zero_matches_expected": close(boot.get("frac_above_zero"), spec["expected_frac_above_zero"]),
            "frac_above_zero_below_gate": float(boot.get("frac_above_zero")) < 0.95,
            "master_prereg_matches": prereg.get("master_prereg_id") == "t1_ceiling_push_20260510_134829",
            "slot_id_matches": prereg.get("slot_id") == slot_id,
        }
        if slot_id == "C":
            overlap = screen.get("overlap_per_fold_summary", {})
            checks["selection_rule_changed"] = 150 <= float(overlap.get("mean", 0)) <= 300
        row = {
            "slot": slot_id,
            "name": spec["name"],
            "screen": spec["screen"].relative_to(ROOT).as_posix(),
            "preregistration": spec["prereg"].relative_to(ROOT).as_posix(),
            "n_subjects": screen.get("n_subjects"),
            "delta_mean": screen.get("delta_mean"),
            "delta_std": screen.get("delta_std"),
            "frac_above_zero": boot.get("frac_above_zero"),
            "screen_gate_pass": screen.get("screen_gate_pass"),
            "checks": checks,
        }
        if slot_id == "C":
            row["overlap_per_fold_summary"] = screen.get("overlap_per_fold_summary")
        rows.append(row)
        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            hard_failures.append({"slot": slot_id, "failed_checks": failed})

    closure_findings_ok = all(
        marker in findings
        for marker in [
            "F-t1-iter37-slotA-screen-correction-20260510",
            "F-t1-iter38-slotB-screen-FAIL-20260510",
            "F-t1-iter39-slotC-screen-FAIL-20260510",
            "F-t1-ceiling-push-20260510-CLOSURE",
        ]
    )
    if not closure_findings_ok:
        hard_failures.append({"slot": "findings", "failed_checks": ["closure_findings_missing"]})

    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_t1_ceiling_push_closure.py",
        "objective": "Verify the T1 architecture ceiling-push family closure against actual screen artifacts.",
        "not_a_model_headline_update": True,
        "passed": not hard_failures,
        "decision": "t1_ceiling_push_closed_iter34_holds" if not hard_failures else "t1_ceiling_push_closure_incomplete",
        "master_preregistration": "results/preregistration_t1_ceiling_push_20260510_134829.json",
        "screen_gate": "delta_mean >= +0.025 and paired-bootstrap frac_above_zero >= 0.95",
        "slots": rows,
        "hard_failures": hard_failures,
        "claim": "All executed T1 ceiling-push slots failed the 5-fold screen; no LOOCV promotion; iter34 remains strongest candidate.",
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# T1 Ceiling-Push Closure Audit - 2026-05-10",
        "",
        "This verifies failure/closure artifacts, not a new model headline.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Screen gate: `{report['screen_gate']}`",
        "",
        "## Slots",
        "",
        "| Slot | Delta vs iter34 | frac>0 | Gate pass | Screen |",
        "|---|---:|---:|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['slot']} | `{row['delta_mean']:+.4f}` | `{row['frac_above_zero']:.3f}` | `{row['screen_gate_pass']}` | `{row['screen']}` |"
        )
    lines.extend(
        [
            "",
            "## Decision",
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
