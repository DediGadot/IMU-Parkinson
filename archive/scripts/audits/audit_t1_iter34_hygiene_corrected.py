#!/usr/bin/env python3
"""Classify the T1 iter34 hygiene-corrected lockbox rerun.

This is a status/result audit for the N=92 valid-range auxiliary-label rerun.
It does not launch the experiment and it does not update canonicals.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
PREREG = RESULTS / "preregistration_t1_iter34_hygiene_corrected_20260510_200037.json"
OUT_JSON = RESULTS / "t1_iter34_hygiene_corrected_status_20260510.json"
OUT_MD = RESULTS / "t1_iter34_hygiene_corrected_status_20260510.md"

ORIGINAL_ITER34_CCC = 0.7366
ITER12_HONEST_CCC = 0.6550
EXPECTED_N = 92
EXPECTED_ABSENT_SIDS = {"NLS036", "WPD002"}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def result_candidates() -> list[Path]:
    if not PREREG.exists():
        return []
    prereg_name = PREREG.name
    candidates: list[Path] = []
    for path in RESULTS.glob("lockbox_t1_iter34_hybrid_*.json"):
        try:
            payload = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("preregistration_file") == prereg_name:
            candidates.append(path)
    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)


def classify_result(payload: dict[str, Any]) -> str:
    ccc = float(payload.get("ccc", float("nan")))
    if ccc >= ORIGINAL_ITER34_CCC:
        return "clean_candidate_meets_or_exceeds_original_iter34"
    if ccc >= 0.7000:
        return "corrected_candidate_degraded_but_above_0_700"
    return "iter34_supersession_warranted_below_0_700"


def build_report() -> dict[str, Any]:
    prereg_payload = load_json(PREREG) if PREREG.exists() else {}
    candidates = result_candidates()
    result_path = candidates[0] if candidates else None
    result_payload = load_json(result_path) if result_path is not None else {}
    result_available = bool(result_payload)

    sids = set(str(sid) for sid in result_payload.get("per_subject", {}).get("sids", []))
    ccc = result_payload.get("ccc")
    n = result_payload.get("n")
    n_subjects = result_payload.get("n_subjects")
    classification = classify_result(result_payload) if result_available else "pending_result"

    checks = [
        check(
            "preregistration exists",
            PREREG.exists(),
            {"path": PREREG.relative_to(ROOT).as_posix()},
        ),
        check(
            "preregistration declares hygiene-corrected N=92 rerun",
            prereg_payload.get("is_hygiene_correction_replication") is True
            and prereg_payload.get("eval_protocol", {}).get("expected_n_subjects") == EXPECTED_N
            and prereg_payload.get("variant") == "hybrid_3base_8item_chain_hygiene_corrected",
            {
                "variant": prereg_payload.get("variant"),
                "expected_n_subjects": prereg_payload.get("eval_protocol", {}).get("expected_n_subjects"),
            },
        ),
    ]
    if not result_available:
        checks.append(
            check(
                "hygiene-corrected lockbox result exists",
                False,
                {
                    "expected_preregistration_file": PREREG.name,
                    "candidates_found": [path.name for path in candidates],
                },
            )
        )
    else:
        checks.extend(
            [
                check(
                    "result binds to hygiene-corrected preregistration",
                    result_payload.get("preregistration_file") == PREREG.name,
                    {"result": result_path.relative_to(ROOT).as_posix(), "preregistration_file": result_payload.get("preregistration_file")},
                ),
                check(
                    "result cohort has expected N=92",
                    n == EXPECTED_N and n_subjects == EXPECTED_N and len(sids) == EXPECTED_N,
                    {"n": n, "n_subjects": n_subjects, "per_subject_sids": len(sids)},
                ),
                check(
                    "invalid/missing-auxiliary subjects are absent",
                    EXPECTED_ABSENT_SIDS.isdisjoint(sids),
                    {"expected_absent_sids": sorted(EXPECTED_ABSENT_SIDS), "present": sorted(EXPECTED_ABSENT_SIDS & sids)},
                ),
                check(
                    "result has finite CCC and MAE",
                    isinstance(ccc, (float, int)) and isinstance(result_payload.get("mae"), (float, int)),
                    {"ccc": ccc, "mae": result_payload.get("mae")},
                ),
                check(
                    "result metadata keeps hygiene rerun non-canonical",
                    result_payload.get("is_canonical_update") is False
                    and result_payload.get("canonical_update_policy")
                    == "disabled_for_hygiene_correction_replication",
                    {
                        "is_canonical_update": result_payload.get("is_canonical_update"),
                        "canonical_update_policy": result_payload.get("canonical_update_policy"),
                    },
                ),
                check(
                    "decision-rule classification recorded",
                    classification
                    in {
                        "clean_candidate_meets_or_exceeds_original_iter34",
                        "corrected_candidate_degraded_but_above_0_700",
                        "iter34_supersession_warranted_below_0_700",
                    },
                    {
                        "classification": classification,
                        "ccc": ccc,
                        "original_iter34_ccc": ORIGINAL_ITER34_CCC,
                        "iter12_honest_ccc": ITER12_HONEST_CCC,
                    },
                ),
            ]
        )

    hard_failures = [row for row in checks if not row["passed"]]
    if not result_available:
        hard_failures = [row for row in hard_failures if row["name"] != "hygiene-corrected lockbox result exists"]
    return {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_t1_iter34_hygiene_corrected.py",
        "not_a_model_run": True,
        "goal_complete": False,
        "result_available": result_available,
        "status": classification,
        "passed": not hard_failures,
        "hard_failures": hard_failures,
        "checks": checks,
        "preregistration": PREREG.relative_to(ROOT).as_posix(),
        "result": result_path.relative_to(ROOT).as_posix() if result_path else None,
        "ccc": ccc,
        "decision_rules": {
            "clean_candidate": f"ccc >= {ORIGINAL_ITER34_CCC:.4f}",
            "degraded_candidate": f"0.7000 <= ccc < {ORIGINAL_ITER34_CCC:.4f}",
            "supersession_warranted": "ccc < 0.7000",
        },
    }


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    report = build_report()
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# T1 Iter34 Hygiene-Corrected Status - 2026-05-10",
        "",
        "This audit classifies the pre-registered N=92 hygiene-corrected iter34 rerun. It does not launch a model run.",
        "",
        f"- Result available: `{report['result_available']}`",
        f"- Status: `{report['status']}`",
        f"- Passed: `{report['passed']}`",
        f"- Hard failures: `{len(report['hard_failures'])}`",
        f"- Result: `{report['result']}`",
        f"- CCC: `{report['ccc']}`",
        "",
        "## Checks",
        "",
    ]
    for row in report["checks"]:
        lines.append(f"- `{row['passed']}` {row['name']}")
    lines.extend(["", f"Machine-readable report: `{OUT_JSON.relative_to(ROOT).as_posix()}`", ""])
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "result_available": report["result_available"],
                "status": report["status"],
                "hard_failures": len(report["hard_failures"]),
            },
            indent=2,
            sort_keys=True,
        )
    )
    if report["hard_failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
