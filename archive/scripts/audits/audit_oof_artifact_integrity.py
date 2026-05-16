#!/usr/bin/env python3
"""Verify current OOF .npy artifacts match their JSON per-subject predictions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "oof_artifact_integrity_audit_20260508.json"
OUT_MD = RESULTS / "oof_artifact_integrity_audit_20260508.md"

TOL = 1e-9


ARTIFACTS = [
    {
        "name": "t1_iter12_honest_floor",
        "json": "results/t1_iter12_honest_composite.json",
        "oof": "results/t1_iter12_honest_composite.oof.npy",
        "status": "current_t1_canonical_floor",
    },
    {
        "name": "t1_iter34_hybrid_candidate",
        "json": "results/lockbox_t1_iter34_hybrid_20260506_141720.json",
        "oof": "results/lockbox_t1_iter34_hybrid_20260506_141720.oof.npy",
        "status": "current_t1_strongest_candidate",
    },
    {
        "name": "t1_iter46_etrobust_diagnostic",
        "json": "results/lockbox_t1_iter46_etrobust_20260508_162825.json",
        "oof": "results/lockbox_t1_iter46_etrobust_20260508_162825.oof.npy",
        "status": "negative_diagnostic",
    },
    {
        "name": "t3_iter5_historical_target_contaminated",
        "json": "results/lockbox_t3_iter5_A3_tier1_20260502_171604.json",
        "oof": "results/lockbox_t3_iter5_A3_tier1_20260502_171604.oof.npy",
        "status": "historical_target_contaminated",
    },
]


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def audit_artifact(spec: dict[str, str]) -> dict[str, Any]:
    json_path = ROOT / spec["json"]
    oof_path = ROOT / spec["oof"]
    data = load_json(json_path)
    y_pred = np.asarray(data["per_subject"]["y_pred"], dtype=float)
    oof = np.load(oof_path, allow_pickle=False)
    same_shape = y_pred.shape == oof.shape
    max_abs_diff = float(np.max(np.abs(y_pred - oof))) if same_shape and y_pred.size else None
    passed = bool(same_shape and max_abs_diff is not None and max_abs_diff <= TOL)
    return {
        **spec,
        "json": str(json_path.relative_to(ROOT)),
        "oof": str(oof_path.relative_to(ROOT)),
        "json_n": int(y_pred.shape[0]),
        "oof_shape": list(oof.shape),
        "same_shape": same_shape,
        "max_abs_diff": max_abs_diff,
        "tolerance": TOL,
        "passed": passed,
    }


def build_report() -> dict[str, Any]:
    checks = [audit_artifact(spec) for spec in ARTIFACTS]
    return {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_oof_artifact_integrity.py",
        "policy": "Verify selected current/historical lockbox .oof.npy files are byte-level prediction companions to their JSON per_subject.y_pred arrays.",
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
    }


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# OOF Artifact Integrity Audit - 2026-05-08",
        "",
        report["policy"],
        "",
        f"- Passed: `{report['passed']}`",
        f"- Checks: `{len(report['checks'])}`",
        "",
        "## Checks",
        "",
    ]
    for check in report["checks"]:
        lines.extend(
            [
                f"### {check['name']}",
                "",
                f"- Status: `{check['status']}`",
                f"- Passed: `{check['passed']}`",
                f"- JSON: `{check['json']}`",
                f"- OOF: `{check['oof']}`",
                f"- JSON N: `{check['json_n']}`",
                f"- OOF shape: `{check['oof_shape']}`",
                f"- Max abs diff: `{check['max_abs_diff']}`",
                "",
            ]
        )
    lines.extend(["", f"Machine-readable report: `{OUT_JSON.relative_to(ROOT)}`", ""])
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    report = build_report()
    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_markdown(report)
    print(f"Wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"Wrote {OUT_MD.relative_to(ROOT)}")
    print(json.dumps({"passed": report["passed"], "checks": len(report["checks"])}, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
