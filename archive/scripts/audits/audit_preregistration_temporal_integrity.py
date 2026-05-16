#!/usr/bin/env python3
"""Audit pre-registration ordering and formula links for reportable artifacts."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "preregistration_temporal_integrity_audit_20260508.json"
OUT_MD = RESULTS / "preregistration_temporal_integrity_audit_20260508.md"


ARTIFACTS = [
    {
        "name": "t1_iter12_honest_floor",
        "status": "current_t1_canonical_floor",
        "prereg": "results/preregistration_t1_iter12_honest_20260503_053105.json",
        "result": "results/t1_iter12_honest_composite.json",
    },
    {
        "name": "t1_iter34_hybrid_candidate",
        "status": "current_t1_strongest_candidate",
        "prereg": "results/preregistration_t1_iter34_hybrid_20260506_135932.json",
        "result": "results/lockbox_t1_iter34_hybrid_20260506_141720.json",
    },
    {
        "name": "t1_iter46_etrobust_diagnostic",
        "status": "negative_diagnostic",
        "prereg": "results/preregistration_t1_iter46_etrobust_20260508_160501.json",
        "result": "results/lockbox_t1_iter46_etrobust_20260508_162825.json",
    },
    {
        "name": "t3_iter47_validrange_current",
        "status": "current_t3_audit_truth",
        "prereg": "results/preregistration_t3_iter47_invalidcode_20260508_194605.json",
        "result": "results/iter47_invalidcode_20260508_194605.json",
    },
    {
        "name": "t3_iter47_validrange_loso",
        "status": "current_t3_loso_audit_truth",
        "prereg": "results/preregistration_t3_iter47_invalidcode_loso_20260508_195424.json",
        "result": "results/iter47_invalidcode_loso_20260508_195424.json",
    },
    {
        "name": "t3_iter39_fogstar_zeroshot",
        "status": "external_validity_partial",
        "prereg": "results/preregistration_t3_iter39_fogstar_zeroshot_20260508_143717.json",
        "result": "results/iter39_fogstar_zeroshot_20260508_143717.json",
    },
    {
        "name": "t3_iter49_cops_zeroshot",
        "status": "external_validity_partial",
        "prereg": "results/preregistration_t3_iter49_cops.json",
        "result": "results/iter49_cops_zeroshot.json",
    },
    {
        "name": "t3_iter51_tlvmc_defog_zeroshot",
        "status": "external_validity_partial",
        "prereg": "results/preregistration_t3_iter51_tlvmc_defog_zeroshot.json",
        "result": "results/iter51_tlvmc_defog_zeroshot.json",
    },
    {
        "name": "t3_iter5_historical",
        "status": "historical_target_contaminated",
        "prereg": "results/preregistration_t3_iter5_20260502_171604.json",
        "result": "results/lockbox_t3_iter5_A3_tier1_20260502_171604.json",
    },
]


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    s = str(value).strip()
    if re.fullmatch(r"\d{8}_\d{6}", s):
        return datetime.strptime(s, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def filename_datetime(path: Path) -> datetime | None:
    match = re.search(r"(20\d{6})_(\d{6})", path.name)
    if not match:
        return None
    return datetime.strptime("_".join(match.groups()), "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)


def best_time(path: Path, data: dict[str, Any]) -> tuple[datetime | None, str | None]:
    fields = ["created_at_utc", "timestamp_utc", "iso_datetime", "timestamp", "created_at_local"]
    for field in fields:
        dt = parse_datetime(data.get(field))
        if dt is not None:
            return dt, field
    dt = filename_datetime(path)
    if dt is not None:
        return dt, "filename"
    return None, None


def prereg_reference(result: dict[str, Any]) -> str | None:
    for key in ["preregistration_file", "preregistration"]:
        value = result.get(key)
        if value:
            return Path(str(value)).name
    return None


def result_formula(result: dict[str, Any]) -> str | None:
    return result.get("formula_sha256") or result.get("preregistration_formula_sha256")


def audit_one(spec: dict[str, str]) -> dict[str, Any]:
    prereg_path = ROOT / spec["prereg"]
    result_path = ROOT / spec["result"]
    prereg = load_json(prereg_path)
    result = load_json(result_path)

    prereg_time, prereg_time_source = best_time(prereg_path, prereg)
    result_time, result_time_source = best_time(result_path, result)
    temporal_ok: bool | None
    if prereg_time and result_time:
        # Filename timestamps are second-resolution. Treat same-second prereg and
        # result files as ordered if the prereg only exceeds the filename by
        # subsecond precision.
        grace = timedelta(seconds=1) if result_time_source == "filename" else timedelta(0)
        temporal_ok = prereg_time <= result_time + grace
    else:
        temporal_ok = None

    pre_sha = prereg.get("formula_sha256")
    res_sha = result_formula(result)
    if pre_sha and res_sha:
        formula_status = "match" if pre_sha == res_sha else "mismatch"
    elif pre_sha and not res_sha:
        formula_status = "prereg_only_result_lacks_formula_link"
    else:
        formula_status = "not_recorded_legacy_or_no_formula"

    ref_name = prereg_reference(result)
    reference_ok = ref_name is None or ref_name == prereg_path.name
    if result_path.name == "iter49_cops_zeroshot.json":
        # Stable iter49 output links by formula hash, not path, after copying the
        # timestamped preregistration to the stable prereg filename.
        reference_ok = bool(pre_sha and res_sha and pre_sha == res_sha)

    warnings = []
    if prereg.get("git_sha") == "unknown" or prereg.get("git_head") == "unknown":
        warnings.append("prereg_git_sha_unknown")
    if formula_status in {"prereg_only_result_lacks_formula_link", "not_recorded_legacy_or_no_formula"}:
        warnings.append(formula_status)
    if prereg_path.stat().st_mtime > result_path.stat().st_mtime:
        warnings.append("filesystem_mtime_not_temporal_order_authority")
    if temporal_ok is None:
        warnings.append("embedded_or_filename_result_time_missing")

    hard_failures = []
    if temporal_ok is False:
        hard_failures.append("pre_registration_time_not_before_result_time")
    if not reference_ok:
        hard_failures.append("result_does_not_reference_expected_preregistration")
    if formula_status == "mismatch":
        hard_failures.append("formula_sha256_mismatch")

    return {
        **spec,
        "prereg": str(prereg_path.relative_to(ROOT)),
        "result": str(result_path.relative_to(ROOT)),
        "prereg_time_utc": prereg_time.isoformat() if prereg_time else None,
        "prereg_time_source": prereg_time_source,
        "result_time_utc": result_time.isoformat() if result_time else None,
        "result_time_source": result_time_source,
        "temporal_ok": temporal_ok,
        "result_preregistration_reference": ref_name,
        "reference_ok": reference_ok,
        "prereg_formula_sha256": pre_sha,
        "result_formula_sha256": res_sha,
        "formula_status": formula_status,
        "warnings": warnings,
        "hard_failures": hard_failures,
        "passed": not hard_failures,
    }


def build_report() -> dict[str, Any]:
    checks = [audit_one(spec) for spec in ARTIFACTS]
    warnings = [
        {"name": check["name"], "warning": warning}
        for check in checks
        for warning in check["warnings"]
    ]
    hard_failures = [
        {"name": check["name"], "failure": failure}
        for check in checks
        for failure in check["hard_failures"]
    ]
    return {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_preregistration_temporal_integrity.py",
        "policy": "Use embedded timestamps or filename timestamps, not pulled-file mtimes, to verify pre-registration precedes result generation; compare formula hashes when both sides record them.",
        "passed": not hard_failures,
        "checks": checks,
        "warnings": warnings,
        "hard_failures": hard_failures,
    }


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# Pre-Registration Temporal Integrity Audit - 2026-05-08",
        "",
        report["policy"],
        "",
        f"- Passed: `{report['passed']}`",
        f"- Checks: `{len(report['checks'])}`",
        f"- Warnings: `{len(report['warnings'])}`",
        f"- Hard failures: `{len(report['hard_failures'])}`",
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
                f"- Prereg: `{check['prereg']}`",
                f"- Result: `{check['result']}`",
                f"- Prereg time: `{check['prereg_time_utc']}` via `{check['prereg_time_source']}`",
                f"- Result time: `{check['result_time_utc']}` via `{check['result_time_source']}`",
                f"- Temporal ok: `{check['temporal_ok']}`",
                f"- Reference ok: `{check['reference_ok']}`",
                f"- Formula status: `{check['formula_status']}`",
                f"- Warnings: `{check['warnings']}`",
                f"- Hard failures: `{check['hard_failures']}`",
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
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "checks": len(report["checks"]),
                "warnings": len(report["warnings"]),
                "hard_failures": len(report["hard_failures"]),
            },
            indent=2,
        )
    )
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
