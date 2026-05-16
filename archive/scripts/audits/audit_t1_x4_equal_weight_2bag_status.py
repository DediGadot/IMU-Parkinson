#!/usr/bin/env python3
"""Audit the T1 X4 equal-weight 2-bag near-miss evidence.

This is not a canonical claim update. It verifies that the X4 V2+V3-GSP
equal-weight bag is the strongest current in-cohort T1 lift, but still misses
the pre-existing full-cohort promotion gates.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
REAL_JSON = RESULTS / "lockbox_t1_X4_equal_weight_2bag_20260516T074106Z.json"
SCRAMBLED_JSON = (
    RESULTS / "lockbox_t1_X4_equal_weight_2bag_20260516T074106Z_scrambled_y.json"
)
SID_SHUFFLE_JSON = (
    RESULTS / "lockbox_t1_X4_equal_weight_2bag_20260516T074105Z_sid_shuffle.json"
)
CANARY_JSON = (
    RESULTS / "lockbox_t1_X4_equal_weight_2bag_20260516T074105Z_canary_noise.json"
)
TRANSDUCTIVE_JSON = (
    RESULTS / "lockbox_t1_X4_equal_weight_2bag_20260516T074105Z_transductive.json"
)
SANITY_Y_NAN_JSON = (
    RESULTS / "lockbox_t1_X4_equal_weight_2bag_20260516T074105Z_sanityYnan.json"
)
PREREG_JSON = RESULTS / "preregistration_t1_post_closure_X_series_20260516.json"
OUT_JSON = RESULTS / "t1_x4_equal_weight_2bag_status_20260516.json"
OUT_MD = RESULTS / "t1_x4_equal_weight_2bag_status_20260516.md"

T1_BASELINE_CCC = 0.7170378403014925
T1_PROMOTION_DELTA = 0.025
PROMOTION_FRAC_POS = 0.95


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must contain a JSON object")
    return payload


def approx(value: Any, expected: float, tol: float = 5e-4) -> bool:
    try:
        return abs(float(value) - expected) <= tol
    except (TypeError, ValueError):
        return False


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def mode_summary(path: Path) -> dict[str, Any]:
    obj = load_json(path)
    bag = obj.get("bag", {})
    seed_a = obj.get("bootstrap_seed_A", {})
    seed_b = obj.get("bootstrap_seed_B", {})
    return {
        "path": rel(path),
        "null_mode": obj.get("null_mode"),
        "sanity_y_nan": obj.get("sanity_y_nan"),
        "ccc": bag.get("loocv_ccc"),
        "mae": bag.get("loocv_mae"),
        "delta_ccc": bag.get("delta_ccc"),
        "delta_mae": bag.get("delta_mae"),
        "delta_pearson_r": bag.get("delta_pearson_r"),
        "frac_positive_seed_A": seed_a.get("frac_pos"),
        "frac_positive_seed_B": seed_b.get("frac_pos"),
        "verdict": obj.get("verdict_provisional"),
        "predictor_alignment_corr_v2_v3": obj.get("predictor_alignment_corr_v2_v3"),
        "fivefold_screen": obj.get("fivefold_screen"),
    }


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    prereg = load_json(PREREG_JSON)
    real = mode_summary(REAL_JSON)
    scrambled = mode_summary(SCRAMBLED_JSON)
    sid_shuffle = mode_summary(SID_SHUFFLE_JSON)
    canary = mode_summary(CANARY_JSON)
    transductive = mode_summary(TRANSDUCTIVE_JSON)
    sanity_y_nan = mode_summary(SANITY_Y_NAN_JSON)

    frac_min = min(real["frac_positive_seed_A"], real["frac_positive_seed_B"])
    promotion_gate_pass = (
        real["delta_ccc"] >= T1_PROMOTION_DELTA
        and frac_min >= PROMOTION_FRAC_POS
    )
    canary_delta_shift = abs(canary["delta_ccc"] - real["delta_ccc"])
    sanity_delta_shift = abs(sanity_y_nan["delta_ccc"] - real["delta_ccc"])

    checks = [
        check(
            "preregistration records X-series context",
            prereg.get("name") == "preregistration_t1_post_closure_X_series_20260516"
            and "X-series" in prereg.get("fwer_policy", {}).get("report_only", {}).get("notes", ""),
            {"path": rel(PREREG_JSON), "name": prereg.get("name")},
        ),
        check(
            "real X4 result is the expected near-miss",
            real["null_mode"] == "real"
            and real["sanity_y_nan"] is False
            and approx(real["ccc"], 0.7345218264, 1e-6)
            and approx(real["delta_ccc"], 0.0174839861, 1e-6)
            and approx(real["delta_mae"], 0.0152489308, 1e-6)
            and approx(real["frac_positive_seed_A"], 0.91, 1e-6)
            and approx(real["frac_positive_seed_B"], 0.9112, 1e-6)
            and real["verdict"] == "NEAR_MISS_PRIMARY_GATE_BOTH_SEEDS"
            and promotion_gate_pass is False,
            {**real, "promotion_gate_pass": promotion_gate_pass},
        ),
        check(
            "scrambled-label null does not clear promotion gate",
            scrambled["null_mode"] == "scrambled_y"
            and scrambled["delta_ccc"] < T1_PROMOTION_DELTA
            and scrambled["frac_positive_seed_A"] < PROMOTION_FRAC_POS
            and scrambled["frac_positive_seed_B"] < PROMOTION_FRAC_POS,
            scrambled,
        ),
        check(
            "SID-shuffle null collapses the V3-GSP contribution",
            sid_shuffle["null_mode"] == "sid_shuffle"
            and sid_shuffle["delta_ccc"] < 0.0
            and sid_shuffle["frac_positive_seed_A"] < 0.01
            and sid_shuffle["frac_positive_seed_B"] < 0.01,
            sid_shuffle,
        ),
        check(
            "canary-noise perturbation preserves the near-miss magnitude",
            canary["null_mode"] == "canary_noise"
            and canary_delta_shift < 0.001
            and canary["verdict"] == "NEAR_MISS_PRIMARY_GATE_BOTH_SEEDS",
            {**canary, "delta_shift_vs_real": canary_delta_shift},
        ),
        check(
            "sanity-y-nan run is identical to real result",
            sanity_y_nan["sanity_y_nan"] is True
            and sanity_delta_shift == 0.0
            and approx(sanity_y_nan["ccc"], real["ccc"], 1e-12),
            {**sanity_y_nan, "delta_shift_vs_real": sanity_delta_shift},
        ),
        check(
            "transductive z-score variant is diagnostic-only and not promotable",
            transductive["null_mode"] == "transductive"
            and transductive["delta_ccc"] < 0.0
            and transductive["frac_positive_seed_A"] == 0.0
            and transductive["frac_positive_seed_B"] == 0.0,
            transductive,
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": Path(__file__).name,
        "passed": not hard_failures,
        "decision": (
            "x4_near_miss_not_promoted" if not hard_failures else "x4_status_failed"
        ),
        "not_a_canonical_claim_update": True,
        "not_a_model_rerun": True,
        "goal_complete": False,
        "baseline_ccc": T1_BASELINE_CCC,
        "promotion_gate": {
            "delta_min": T1_PROMOTION_DELTA,
            "frac_positive_min": PROMOTION_FRAC_POS,
            "passes": promotion_gate_pass,
        },
        "real_result": real,
        "null_results": {
            "scrambled_y": scrambled,
            "sid_shuffle": sid_shuffle,
            "canary_noise": canary,
            "transductive": transductive,
            "sanity_y_nan": sanity_y_nan,
        },
        "checks": checks,
        "hard_failures": hard_failures,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# T1 X4 Equal-Weight 2-Bag Status - 2026-05-16",
        "",
        "This audit verifies the X4 near-miss evidence. It is not a canonical claim update.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Goal complete: `{report['goal_complete']}`",
        f"- Real CCC: `{real['ccc']}`",
        f"- Delta vs iter34: `{real['delta_ccc']}`",
        f"- frac>0 seeds: `{real['frac_positive_seed_A']}` / `{real['frac_positive_seed_B']}`",
        f"- Promotion gate pass: `{promotion_gate_pass}`",
        "",
        "## Checks",
        "",
    ]
    lines.extend(f"- `{row['passed']}` {row['name']}" for row in checks)
    lines.extend(["", f"Machine-readable report: `{rel(OUT_JSON)}`", ""])
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(json.dumps({"passed": report["passed"], "hard_failures": len(hard_failures)}, indent=2))
    if hard_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
