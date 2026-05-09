#!/usr/bin/env python3
"""Build a fail-closed map of current per-item UPDRS-III evidence.

This is a reporting/provenance audit. It reads existing per-item lockbox and
composite artifacts, classifies each item by its current claim scope, and writes
a compact table for handoff. It does not refit models or promote any per-item
composition route.
"""

from __future__ import annotations

import csv
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "per_item_evidence_map_20260508.json"
OUT_MD = RESULTS / "per_item_evidence_map_20260508.md"

ITER8_SUMMARY = RESULTS / "peritem_lockbox_summary_20260430_143044.csv"
ITER8_COMPOSITE = RESULTS / "peritem_composite_20260430_143044.json"
ITER12_T1 = RESULTS / "t1_iter12_honest_composite.json"
ITER17_COMBINED = RESULTS / "lockbox_peritem_iter17_combined_20260503_221544.json"
ITER17_PREREG = RESULTS / "preregistration_peritem_iter17_20260503_221544.json"
T3_BACKFILL_WINNERS = RESULTS / "peritem_t3_backfill_winners.json"

T1_ITEMS = {9, 10, 11, 12, 13, 14}
ITER17_HEADLINE_KEYS = {
    15: "item15_item_only",
    18: "item18_hy_residual_item_v2",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def clean(value: Any) -> Any:
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(parsed) else parsed


def approx(value: Any, expected: float, tol: float = 5e-4) -> bool:
    parsed = as_float(value)
    return parsed is not None and abs(parsed - expected) <= tol


def load_iter8_summary() -> dict[int, dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = {}
    with ITER8_SUMMARY.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            item = int(row["item"])
            lockbox_artifact = Path("results") / f"lockbox_peritem_{item}_{row['variant']}_20260430_143044.json"
            lockbox_path = ROOT / lockbox_artifact
            lockbox_n = 94
            if lockbox_path.exists():
                lockbox_n = int(load_json(lockbox_path).get("n_subjects", lockbox_n))
            rows[item] = {
                "item": item,
                "variant": row["variant"],
                "ccc": as_float(row["loocv_ccc_mean"]),
                "ccc_std": as_float(row["loocv_ccc_std"]),
                "mae": as_float(row["loocv_mae_mean"]),
                "n": lockbox_n,
                "screening_5split_ccc": as_float(row["screening_5split_ccc"]),
                "source_artifact": str(ITER8_SUMMARY.relative_to(ROOT)),
                "individual_lockbox_artifact": str(lockbox_artifact),
            }
    return rows


def item_row_from_iter8(item: int, iter8: dict[int, dict[str, Any]]) -> dict[str, Any]:
    base = dict(iter8[item])
    if item in T1_ITEMS:
        base.update(
            {
                "status": "current_t1_iter12_component",
                "claim_scope": "component_of_canonical_t1_iter12_floor_not_standalone_headline",
                "caveat": "Per-item CCC is descriptive; the current reportable T1 number is the coherent iter12 sum over items 9-14.",
            }
        )
    else:
        base.update(
            {
                "status": "historical_iter8_per_item_lockbox_supplementary",
                "claim_scope": "historical_per_item_lockbox_supplementary_not_current_t1_or_t3_route",
                "caveat": "Useful for item-level audit context only; not a current composite or deployment headline.",
            }
        )
    return base


def build_rows() -> list[dict[str, Any]]:
    iter8 = load_iter8_summary()
    iter17 = load_json(ITER17_COMBINED)
    backfill = load_json(T3_BACKFILL_WINNERS)
    headlines = iter17.get("headlines", {})

    rows: list[dict[str, Any]] = []
    for item in range(1, 19):
        if item in {1, 2, 3}:
            rows.append(
                {
                    "item": item,
                    "status": "missing_or_backfill_only_unobservable",
                    "variant": backfill.get(str(item)),
                    "ccc": None,
                    "ccc_std": None,
                    "mae": None,
                    "n": None,
                    "source_artifact": str(T3_BACKFILL_WINNERS.relative_to(ROOT)),
                    "individual_lockbox_artifact": None,
                    "claim_scope": "no_current_reportable_loocv_per_item_lockbox",
                    "caveat": "Only backfill/screening metadata exists for this current map; no current reportable per-item LOOCV CCC.",
                }
            )
            continue

        if item in ITER17_HEADLINE_KEYS:
            key = ITER17_HEADLINE_KEYS[item]
            headline = headlines.get(key, {})
            historical = dict(iter8[item])
            rows.append(
                {
                    "item": item,
                    "status": "iter17_reportable_per_item_win",
                    "variant": headline.get("variant"),
                    "ccc": headline.get("ccc"),
                    "ccc_std": headline.get("seed_std"),
                    "mae": headline.get("mae"),
                    "n": headline.get("n"),
                    "source_artifact": str(ITER17_COMBINED.relative_to(ROOT)),
                    "individual_lockbox_artifact": str(
                        Path("results")
                        / (
                            f"lockbox_peritem_{item}_iter17hyp_"
                            f"{headline.get('variant')}_20260503_221544.json"
                        )
                    ),
                    "claim_scope": "supplementary_per_item_lockbox_win_not_t1_t3_composite_update",
                    "caveat": (
                        "Reportable as a supplementary per-item win only. It does not update canonical T1/T3 composites; "
                        "the T3 per-item composite route is dead from variance compounding."
                    ),
                    "baseline_ccc": headline.get("baseline_ccc"),
                    "delta_vs_baseline": headline.get("delta_vs_baseline"),
                    "historical_iter8_metric": {
                        "variant": historical.get("variant"),
                        "ccc": historical.get("ccc"),
                        "mae": historical.get("mae"),
                        "source_artifact": historical.get("source_artifact"),
                    },
                }
            )
            continue

        rows.append(item_row_from_iter8(item, iter8))

    return clean(rows)


def source_artifacts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    paths = {
        ITER8_SUMMARY,
        ITER8_COMPOSITE,
        ITER12_T1,
        ITER17_COMBINED,
        ITER17_PREREG,
        T3_BACKFILL_WINNERS,
    }
    for row in rows:
        artifact = row.get("individual_lockbox_artifact")
        if artifact:
            paths.add(ROOT / artifact)
    records = []
    for path in sorted(paths):
        records.append(
            {
                "path": str(path.relative_to(ROOT)),
                "exists": path.exists(),
                "bytes": path.stat().st_size if path.exists() and path.is_file() else None,
            }
        )
    return records


def build_report() -> dict[str, Any]:
    rows = build_rows()
    t1 = load_json(ITER12_T1)
    composite = load_json(ITER8_COMPOSITE)
    composites = composite.get("composites", {})
    status_counts = Counter(row["status"] for row in rows)
    artifacts = source_artifacts(rows)
    missing_artifacts = [a["path"] for a in artifacts if not a["exists"]]

    row_by_item = {row["item"]: row for row in rows}
    key_checks = [
        {
            "name": "eighteen_item_rows_present",
            "passed": len(rows) == 18 and sorted(row_by_item) == list(range(1, 19)),
            "evidence": {"n_rows": len(rows), "items": sorted(row_by_item)},
        },
        {
            "name": "status_counts_match_current_claim_scope",
            "passed": dict(status_counts)
            == {
                "missing_or_backfill_only_unobservable": 3,
                "historical_iter8_per_item_lockbox_supplementary": 7,
                "current_t1_iter12_component": 6,
                "iter17_reportable_per_item_win": 2,
            },
            "evidence": dict(status_counts),
        },
        {
            "name": "t1_component_item9_metric_matches_iter8_batch",
            "passed": approx(row_by_item[9].get("ccc"), 0.4436666667),
            "evidence": row_by_item[9],
        },
        {
            "name": "t1_component_item12_metric_matches_iter8_batch",
            "passed": approx(row_by_item[12].get("ccc"), 0.5928),
            "evidence": row_by_item[12],
        },
        {
            "name": "iter17_item15_metric_matches_lockbox",
            "passed": approx(row_by_item[15].get("ccc"), 0.1099)
            and row_by_item[15].get("n") == 94,
            "evidence": row_by_item[15],
        },
        {
            "name": "iter17_item18_metric_matches_lockbox",
            "passed": approx(row_by_item[18].get("ccc"), 0.4858)
            and row_by_item[18].get("n") == 93,
            "evidence": row_by_item[18],
        },
        {
            "name": "canonical_t1_sum_is_current_composite",
            "passed": approx(t1.get("ccc"), 0.6550) and approx(t1.get("mae"), 1.5614, 1e-3),
            "evidence": {"ccc": t1.get("ccc"), "mae": t1.get("mae"), "n": t1.get("n")},
        },
        {
            "name": "t3_per_item_sum_is_historical_dead_route",
            "passed": approx(composites.get("T3_sum", {}).get("ccc"), 0.2646)
            and composites.get("T3_sum", {}).get("items_used") == list(range(1, 19)),
            "evidence": composites.get("T3_sum", {}),
        },
        {
            "name": "all_source_artifacts_exist",
            "passed": not missing_artifacts,
            "evidence": {"missing": missing_artifacts},
        },
    ]

    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_per_item_evidence_map.py",
        "policy": (
            "Per-item CCCs must be reported with their current claim scope. "
            "Items 9-14 are components of the canonical iter12 T1 floor, items 15 and 18 are "
            "supplementary iter17 per-item wins, items 4-8/16/17 are historical iter8 lockbox "
            "context, and items 1-3 remain backfill-only for this current map. The T3 per-item "
            "sum is a historical dead route, not a current T3 headline."
        ),
        "passed": all(check["passed"] for check in key_checks),
        "status_counts": dict(status_counts),
        "composites": {
            "t1_iter12_sum": {
                "status": "current_canonical_floor",
                "ccc": t1.get("ccc"),
                "mae": t1.get("mae"),
                "n": t1.get("n"),
                "items_used": [9, 10, 11, 12, 13, 14],
                "source_artifact": str(ITER12_T1.relative_to(ROOT)),
            },
            "t3_per_item_sum_historical": {
                "status": "historical_dead_route_not_current_t3",
                "ccc": composites.get("T3_sum", {}).get("ccc"),
                "mae": composites.get("T3_sum", {}).get("mae"),
                "n": composites.get("T3_sum", {}).get("n"),
                "items_used": composites.get("T3_sum", {}).get("items_used"),
                "source_artifact": str(ITER8_COMPOSITE.relative_to(ROOT)),
            },
        },
        "rows": rows,
        "key_checks": key_checks,
        "source_artifacts": artifacts,
        "missing_artifacts": missing_artifacts,
        "next_action": (
            "Do not launch another WearGait-only per-item composite. Use this map for manuscript "
            "and handoff evidence; new composite claims require new data or a genuinely new target representation."
        ),
    }
    return clean(report)


def fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# Per-Item Evidence Map - 2026-05-08",
        "",
        report["policy"],
        "",
        f"- Passed: `{report['passed']}`",
        f"- Status counts: `{report['status_counts']}`",
        f"- Missing source artifacts: `{len(report['missing_artifacts'])}`",
        "",
        "## Composite Context",
        "",
        "| Composite | Status | CCC | MAE | N | Items |",
        "|---|---|---:|---:|---:|---|",
    ]
    t1 = report["composites"]["t1_iter12_sum"]
    t3 = report["composites"]["t3_per_item_sum_historical"]
    lines.append(
        f"| T1 iter12 sum | {t1['status']} | {fmt(t1['ccc'])} | {fmt(t1['mae'], 3)} | {t1['n']} | {t1['items_used']} |"
    )
    lines.append(
        f"| T3 per-item sum | {t3['status']} | {fmt(t3['ccc'])} | {fmt(t3['mae'], 3)} | {t3['n']} | 1-18 |"
    )
    lines.extend(
        [
            "",
            "## Item Map",
            "",
            "| Item | Status | Variant | CCC | Std | MAE | N | Claim scope |",
            "|---:|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for row in report["rows"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["item"]),
                    str(row["status"]),
                    str(row.get("variant") or "n/a"),
                    fmt(row.get("ccc")),
                    fmt(row.get("ccc_std")),
                    fmt(row.get("mae"), 3),
                    str(row.get("n") or "n/a"),
                    str(row.get("claim_scope")),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Key Checks",
            "",
            "| Check | Passed |",
            "|---|---:|",
        ]
    )
    for check in report["key_checks"]:
        lines.append(f"| {check['name']} | `{check['passed']}` |")
    lines.extend(["", f"Next action: {report['next_action']}", ""])
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    report = build_report()
    OUT_JSON.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    write_markdown(report)
    print(f"Wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"Wrote {OUT_MD.relative_to(ROOT)}")
    print(f"passed={report['passed']}")
    print(f"rows={len(report['rows'])} status_counts={report['status_counts']}")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
