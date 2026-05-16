"""Audit the canonical T1 iter12 honest composite batch.

This is a provenance/integrity audit, not a model run. It verifies that the
canonical T1 headline is exactly the sum of one coherent pre-registered iter8
per-item lockbox batch, with no per-item swaps.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

import compose_t1_iter12_honest as iter12
from inductive_lib import ccc, full_metrics, mae
from project_paths import RESULTS_DIR, ensure_dir
from updrs_columns import UPDRS_PART3_ITEM_TOTAL_MAX, valid_updrs_item_total


AUDIT_STAMP = "20260508"
EXPECTED_TIMESTAMP = "20260430_143044"
EXPECTED_T1_ITEMS = [9, 10, 11, 12, 13, 14]
EXPECTED_VARIANTS = {
    9: "hy_residual_item",
    10: "item_plus_v2",
    11: "item_dedicated",
    12: "item_plus_v2",
    13: "item_plus_v2",
    14: "item_plus_v2",
}
EXPECTED_METRICS = {"ccc": 0.6550, "mae": 1.5614, "n": 94}
METRIC_TOL = 5e-4


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _round_float(value: float, ndigits: int = 6) -> float:
    return round(float(value), ndigits)


def _record(
    checks: list[dict[str, Any]],
    name: str,
    passed: bool,
    severity: str,
    detail: str,
    observed: Any = None,
) -> None:
    checks.append(
        {
            "name": name,
            "passed": bool(passed),
            "severity": severity,
            "detail": detail,
            "observed": observed,
        }
    )


def _find_summary_row(item: int, variant: str, summary_rows: list[dict[str, str]]) -> dict[str, str] | None:
    for row in summary_rows:
        if int(row["item"]) == item and row["variant"] == variant:
            return row
    return None


def _load_csv_rows(path: Path) -> list[dict[str, str]]:
    import csv

    with path.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_markdown(out_path: Path, audit: dict[str, Any]) -> None:
    hard_failures = [
        c for c in audit["checks"]
        if c["severity"] == "hard" and not c["passed"]
    ]
    warnings = [
        c for c in audit["checks"]
        if c["severity"] == "warning" and not c["passed"]
    ]
    item_rows = audit["item_checks"]
    lines = [
        "# T1 iter12 Batch Integrity Audit",
        "",
        f"- Date stamp: `{AUDIT_STAMP}`",
        f"- Pass: `{audit['pass']}`",
        f"- Hard failures: `{len(hard_failures)}`",
        f"- Warnings: `{len(warnings)}`",
        f"- Timestamp: `{audit['batch']['timestamp']}`",
        f"- Single coherent batch: `{audit['batch']['single_coherent_batch']}`",
        f"- Uses swaps: `{audit['batch']['uses_swaps']}`",
        "",
        "## Composite",
        "",
        f"- N: `{audit['composite']['metrics']['n']}`",
        f"- CCC: `{audit['composite']['metrics']['ccc']}`",
        f"- MAE: `{audit['composite']['metrics']['mae']}`",
        f"- Max abs diff vs stored OOF: `{audit['composite']['max_abs_diff_vs_stored_oof']}`",
        f"- Preregistration: `{audit['composite']['preregistration_file']}`",
        "",
        "## Per-Item Lockboxes",
        "",
        "| Item | Variant | OOF shape | Recomputed CCC | JSON CCC mean | Summary CCC | Target range |",
        "|---:|---|---:|---:|---:|---:|---|",
    ]
    for row in item_rows:
        lines.append(
            "| {item} | `{variant}` | `{shape}` | `{recomputed_ccc}` | `{json_ccc_mean}` | `{summary_ccc}` | `{target_min}`-`{target_max}` |".format(
                **row
            )
        )

    if hard_failures:
        lines.extend(["", "## Hard Failures", ""])
        lines.extend(f"- `{c['name']}`: {c['detail']}" for c in hard_failures)
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- `{c['name']}`: {c['detail']}" for c in warnings)

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            (
                "The canonical T1 iter12 headline is reproducible from the six fixed "
                "iter8-batch per-item OOF files, and the recomputed summed OOF exactly "
                "matches the stored composite OOF. This audit does not promote iter12 "
                "above its original status; it documents that the current canonical "
                "T1 floor has a coherent single-batch provenance."
            ),
            "",
        ]
    )
    out_path.write_text("\n".join(lines), encoding="utf-8")


def run_audit() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    item_checks: list[dict[str, Any]] = []

    _record(
        checks,
        "composer_timestamp_constant",
        iter12.ITER8_TS == EXPECTED_TIMESTAMP,
        "hard",
        f"compose_t1_iter12_honest.ITER8_TS must equal {EXPECTED_TIMESTAMP}.",
        iter12.ITER8_TS,
    )
    _record(
        checks,
        "composer_t1_items_constant",
        list(iter12.T1_ITEMS) == EXPECTED_T1_ITEMS,
        "hard",
        "compose_t1_iter12_honest.T1_ITEMS must stay fixed to items 9-14.",
        list(iter12.T1_ITEMS),
    )
    _record(
        checks,
        "composer_variant_map_constant",
        dict(iter12.ITER8_VARIANTS) == EXPECTED_VARIANTS,
        "hard",
        "compose_t1_iter12_honest.ITER8_VARIANTS must match the iter8 batch map.",
        dict(iter12.ITER8_VARIANTS),
    )

    target_data = iter12.load_composite_target_data()
    sids = np.asarray(target_data["sids"])
    item_targets = target_data["items"]
    y_true = np.asarray(target_data["t1"], dtype=float)
    n_subjects = int(len(sids))
    _record(
        checks,
        "target_subject_count",
        n_subjects == EXPECTED_METRICS["n"],
        "hard",
        "Canonical T1 iter12 target loader must resolve 94 PD subjects.",
        n_subjects,
    )
    _record(
        checks,
        "target_finite_t1",
        bool(np.isfinite(y_true).all()),
        "hard",
        "Summed T1 target must be finite for all loaded subjects.",
        {"n_finite": int(np.isfinite(y_true).sum()), "n_total": int(y_true.size)},
    )

    peritem_composite_path = RESULTS_DIR / f"peritem_composite_{EXPECTED_TIMESTAMP}.json"
    peritem_summary_path = RESULTS_DIR / f"peritem_lockbox_summary_{EXPECTED_TIMESTAMP}.csv"
    canonical_json_path = RESULTS_DIR / "t1_iter12_honest_composite.json"
    canonical_oof_path = RESULTS_DIR / "t1_iter12_honest_composite.oof.npy"

    peritem_composite = _read_json(peritem_composite_path)
    peritem_summary_rows = _load_csv_rows(peritem_summary_path)
    canonical_json = _read_json(canonical_json_path)
    canonical_oof = np.load(canonical_oof_path)

    _record(
        checks,
        "peritem_composite_timestamp",
        peritem_composite.get("timestamp") == EXPECTED_TIMESTAMP,
        "hard",
        "Per-item composite metadata must identify the iter8 lockbox timestamp.",
        peritem_composite.get("timestamp"),
    )
    _record(
        checks,
        "canonical_json_selection_map",
        canonical_json.get("selections") == {str(k): v for k, v in EXPECTED_VARIANTS.items()},
        "hard",
        "Stored T1 iter12 composite selections must match the fixed iter8 variant map.",
        canonical_json.get("selections"),
    )
    _record(
        checks,
        "stored_composite_oof_shape",
        tuple(canonical_oof.shape) == (n_subjects,),
        "hard",
        "Stored T1 iter12 composite OOF must align with the canonical 94-subject SID order.",
        tuple(canonical_oof.shape),
    )
    _record(
        checks,
        "stored_composite_oof_finite",
        bool(np.isfinite(canonical_oof).all()),
        "hard",
        "Stored T1 iter12 composite OOF must be finite.",
        {"n_finite": int(np.isfinite(canonical_oof).sum()), "n_total": int(canonical_oof.size)},
    )

    composite_prereg_name = canonical_json.get("preregistration_file")
    composite_prereg_path = RESULTS_DIR / str(composite_prereg_name)
    composite_prereg_exists = composite_prereg_path.exists()
    _record(
        checks,
        "composite_preregistration_exists",
        composite_prereg_exists,
        "hard",
        "Stored T1 iter12 composite JSON must point to an existing preregistration file.",
        composite_prereg_name,
    )
    composite_prereg = _read_json(composite_prereg_path) if composite_prereg_exists else {}
    _record(
        checks,
        "composite_preregistration_selection_map",
        composite_prereg.get("selections") == {str(k): v for k, v in EXPECTED_VARIANTS.items()},
        "hard",
        "Composite preregistration selections must match the fixed iter8 variant map.",
        composite_prereg.get("selections"),
    )
    _record(
        checks,
        "composite_preregistration_source_files",
        composite_prereg.get("source_files") == {
            str(item): f"lockbox_peritem_{item}_{variant}_{EXPECTED_TIMESTAMP}.oof.npy"
            for item, variant in EXPECTED_VARIANTS.items()
        },
        "hard",
        "Composite preregistration must cite exactly the six expected iter8 OOF files.",
        composite_prereg.get("source_files"),
    )

    oofs: dict[int, np.ndarray] = {}
    for item in EXPECTED_T1_ITEMS:
        variant = EXPECTED_VARIANTS[item]
        prereg_path = RESULTS_DIR / f"preregistration_peritem_{item}_{EXPECTED_TIMESTAMP}.json"
        item_json_path = RESULTS_DIR / f"lockbox_peritem_{item}_{variant}_{EXPECTED_TIMESTAMP}.json"
        item_oof_path = RESULTS_DIR / f"lockbox_peritem_{item}_{variant}_{EXPECTED_TIMESTAMP}.oof.npy"

        prereg_exists = prereg_path.exists()
        item_json_exists = item_json_path.exists()
        item_oof_exists = item_oof_path.exists()
        _record(
            checks,
            f"item_{item}_preregistration_exists",
            prereg_exists,
            "hard",
            f"Item {item} must have a preregistration JSON from the iter8 batch.",
            prereg_path.name,
        )
        _record(
            checks,
            f"item_{item}_lockbox_json_exists",
            item_json_exists,
            "hard",
            f"Item {item} must have a lockbox result JSON for the expected variant.",
            item_json_path.name,
        )
        _record(
            checks,
            f"item_{item}_oof_exists",
            item_oof_exists,
            "hard",
            f"Item {item} must have an OOF array for the expected variant.",
            item_oof_path.name,
        )
        if not (prereg_exists and item_json_exists and item_oof_exists):
            continue

        prereg = _read_json(prereg_path)
        item_json = _read_json(item_json_path)
        arr = np.load(item_oof_path)
        oofs[item] = arr

        _record(
            checks,
            f"item_{item}_prereg_fields",
            prereg.get("item") == item
            and prereg.get("variant") == variant
            and prereg.get("eval") == "loocv"
            and prereg.get("timestamp_prereg") == EXPECTED_TIMESTAMP
            and prereg.get("n_subjects") == EXPECTED_METRICS["n"],
            "hard",
            f"Item {item} preregistration must match item, variant, eval, timestamp, and N.",
            {
                "item": prereg.get("item"),
                "variant": prereg.get("variant"),
                "eval": prereg.get("eval"),
                "timestamp_prereg": prereg.get("timestamp_prereg"),
                "n_subjects": prereg.get("n_subjects"),
            },
        )
        _record(
            checks,
            f"item_{item}_json_fields",
            item_json.get("item") == item
            and item_json.get("variant") == variant
            and item_json.get("eval") == "loocv"
            and item_json.get("n_subjects") == EXPECTED_METRICS["n"]
            and item_json.get("pre_registration") == prereg_path.name,
            "hard",
            f"Item {item} lockbox JSON must match item, variant, eval, N, and prereg pointer.",
            {
                "item": item_json.get("item"),
                "variant": item_json.get("variant"),
                "eval": item_json.get("eval"),
                "n_subjects": item_json.get("n_subjects"),
                "pre_registration": item_json.get("pre_registration"),
            },
        )
        _record(
            checks,
            f"item_{item}_oof_shape",
            tuple(arr.shape) == (n_subjects,),
            "hard",
            f"Item {item} OOF must align with the canonical SID order.",
            tuple(arr.shape),
        )
        _record(
            checks,
            f"item_{item}_oof_finite",
            bool(np.isfinite(arr).all()),
            "hard",
            f"Item {item} OOF must be finite.",
            {"n_finite": int(np.isfinite(arr).sum()), "n_total": int(arr.size)},
        )

        y_item = np.asarray(item_targets[item], dtype=float)
        valid_item_values = [
            valid_updrs_item_total(item, value) is not None
            for value in y_item
        ]
        item_target_valid = bool(np.all(valid_item_values))
        target_min = float(np.nanmin(y_item))
        target_max = float(np.nanmax(y_item))
        expected_max = float(UPDRS_PART3_ITEM_TOTAL_MAX[item])
        _record(
            checks,
            f"item_{item}_target_range",
            item_target_valid and target_min >= 0.0 and target_max <= expected_max,
            "hard",
            f"Item {item} target values must stay within UPDRS item range 0-{expected_max:g}.",
            {"min": target_min, "max": target_max, "expected_max": expected_max},
        )

        item_metrics = {
            "ccc": ccc(y_item, arr),
            "mae": mae(y_item, arr),
        }
        summary_meta = peritem_composite.get("per_item_meta", {}).get(str(item), {})
        summary_row = _find_summary_row(item, variant, peritem_summary_rows)
        summary_csv_ccc = (
            float(summary_row["loocv_ccc_mean"]) if summary_row is not None else None
        )
        summary_json_ccc = summary_meta.get("loocv_ccc")
        item_json_ccc = item_json.get("ccc_mean")

        _record(
            checks,
            f"item_{item}_json_metric_match",
            abs(float(item_json_ccc) - float(summary_json_ccc)) <= METRIC_TOL
            and abs(float(item_json_ccc) - float(summary_csv_ccc)) <= METRIC_TOL,
            "hard",
            f"Item {item} JSON CCC must match summary JSON and CSV lockbox records.",
            {
                "item_json_ccc_mean": item_json_ccc,
                "summary_json_ccc": summary_json_ccc,
                "summary_csv_ccc": summary_csv_ccc,
            },
        )
        _record(
            checks,
            f"item_{item}_recomputed_metric_near_seed_mean",
            abs(float(item_metrics["ccc"]) - float(item_json_ccc)) <= 0.05,
            "warning",
            (
                f"Item {item} recomputed CCC from averaged OOF should be near the "
                "reported mean-of-seed CCC; this is a warning because the historical "
                "JSON stores mean-of-seed metrics while the OOF stores averaged predictions."
            ),
            {
                "recomputed_oof_ccc": item_metrics["ccc"],
                "json_ccc_mean": item_json_ccc,
            },
        )
        item_checks.append(
            {
                "item": item,
                "variant": variant,
                "shape": list(arr.shape),
                "recomputed_ccc": _round_float(item_metrics["ccc"]),
                "recomputed_mae": _round_float(item_metrics["mae"]),
                "json_ccc_mean": _round_float(item_json_ccc),
                "json_mae_mean": _round_float(item_json.get("mae_mean")),
                "summary_ccc": _round_float(summary_csv_ccc),
                "target_min": _round_float(target_min),
                "target_max": _round_float(target_max),
                "target_expected_max": _round_float(expected_max),
                "preregistration": prereg_path.name,
                "json": item_json_path.name,
                "oof": item_oof_path.name,
            }
        )

    have_all_oofs = set(oofs) == set(EXPECTED_T1_ITEMS)
    _record(
        checks,
        "all_six_item_oofs_loaded",
        have_all_oofs,
        "hard",
        "All six expected T1 item OOF arrays must load successfully.",
        sorted(oofs),
    )
    if have_all_oofs:
        y_pred = np.sum(np.column_stack([oofs[item] for item in EXPECTED_T1_ITEMS]), axis=1)
    else:
        y_pred = np.full_like(y_true, np.nan, dtype=float)

    composite_metrics = full_metrics(y_true, y_pred, label="t1_iter12_batch_integrity")
    max_abs_diff = float(np.max(np.abs(y_pred - canonical_oof))) if have_all_oofs else float("nan")
    _record(
        checks,
        "summed_oof_equals_stored_composite_oof",
        have_all_oofs and max_abs_diff <= 1e-12,
        "hard",
        "Summing the six item OOF arrays must exactly reproduce the stored T1 composite OOF.",
        max_abs_diff,
    )
    _record(
        checks,
        "recomputed_composite_metric_matches_json",
        composite_metrics["n"] == canonical_json.get("n")
        and abs(float(composite_metrics["ccc"]) - float(canonical_json.get("ccc"))) <= METRIC_TOL
        and abs(float(composite_metrics["mae"]) - float(canonical_json.get("mae"))) <= METRIC_TOL,
        "hard",
        "Recomputed composite metrics must match the stored canonical T1 iter12 JSON.",
        {"recomputed": composite_metrics, "stored": {k: canonical_json.get(k) for k in ["n", "ccc", "mae"]}},
    )
    _record(
        checks,
        "recomputed_composite_metric_matches_canonical_expected",
        composite_metrics["n"] == EXPECTED_METRICS["n"]
        and abs(float(composite_metrics["ccc"]) - EXPECTED_METRICS["ccc"]) <= METRIC_TOL
        and abs(float(composite_metrics["mae"]) - EXPECTED_METRICS["mae"]) <= METRIC_TOL,
        "hard",
        "Recomputed composite metrics must match the canonical AGENTS.md / CLAUDE.md T1 iter12 numbers.",
        composite_metrics,
    )

    single_batch_source_files = composite_prereg.get("source_files", {})
    source_file_timestamps = {
        name: EXPECTED_TIMESTAMP in str(path)
        for name, path in single_batch_source_files.items()
    }
    single_coherent_batch = (
        set(single_batch_source_files) == {str(item) for item in EXPECTED_T1_ITEMS}
        and all(source_file_timestamps.values())
    )
    _record(
        checks,
        "single_coherent_iter8_batch",
        single_coherent_batch,
        "hard",
        "Composite preregistration must use only one timestamped iter8 batch.",
        single_batch_source_files,
    )

    hard_failed = [
        check["name"]
        for check in checks
        if check["severity"] == "hard" and not check["passed"]
    ]
    warning_failed = [
        check["name"]
        for check in checks
        if check["severity"] == "warning" and not check["passed"]
    ]
    audit = {
        "audit": "t1_iter12_batch_integrity",
        "created_at_utc": "2026-05-08",
        "pass": len(hard_failed) == 0,
        "hard_failures": hard_failed,
        "warnings": warning_failed,
        "batch": {
            "timestamp": EXPECTED_TIMESTAMP,
            "items": EXPECTED_T1_ITEMS,
            "variants": {str(k): v for k, v in EXPECTED_VARIANTS.items()},
            "single_coherent_batch": single_coherent_batch,
            "uses_swaps": False,
            "source_file_timestamps_all_expected": bool(all(source_file_timestamps.values())),
        },
        "subjects": {
            "n": n_subjects,
            "first_sid": str(sids[0]) if n_subjects else None,
            "last_sid": str(sids[-1]) if n_subjects else None,
        },
        "composite": {
            "metrics": composite_metrics,
            "stored_metrics": {k: canonical_json.get(k) for k in ["n", "ccc", "mae", "r", "cal_slope"]},
            "expected_metrics": EXPECTED_METRICS,
            "max_abs_diff_vs_stored_oof": max_abs_diff,
            "preregistration_file": composite_prereg_name,
        },
        "item_checks": item_checks,
        "checks": checks,
        "interpretation": (
            "PASS means the canonical T1 iter12 composite is exactly reproducible "
            "from six fixed per-item OOF arrays in the single iter8 batch "
            "20260430_143044. It does not upgrade the metric; it confirms coherent "
            "provenance for the current honest T1 floor."
        ),
    }
    return audit


def main() -> None:
    ensure_dir(RESULTS_DIR)
    audit = run_audit()
    json_path = RESULTS_DIR / f"t1_iter12_batch_integrity_audit_{AUDIT_STAMP}.json"
    md_path = RESULTS_DIR / f"t1_iter12_batch_integrity_audit_{AUDIT_STAMP}.md"
    json_path.write_text(json.dumps(audit, indent=2, default=str) + "\n", encoding="utf-8")
    _write_markdown(md_path, audit)
    status = "PASS" if audit["pass"] else "FAIL"
    print(f"{status}: wrote {json_path} and {md_path}")
    print(
        "T1 iter12 recomputed: "
        f"CCC={audit['composite']['metrics']['ccc']:.4f}, "
        f"MAE={audit['composite']['metrics']['mae']:.4f}, "
        f"N={audit['composite']['metrics']['n']}"
    )
    print(f"Hard failures: {len(audit['hard_failures'])}; warnings: {len(audit['warnings'])}")


if __name__ == "__main__":
    main()
