"""Audit the T3 Slot F CQR-width deployable-secondary replication.

This is a claim-governance audit, not a model run. It checks whether the
original Slot F CQR-width retained-subset result and the disjoint-seed
replication clear the current replicated-uncorrected deployable-secondary gate.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "t3_slotF_replication_audit_20260515.json"
OUT_MD = RESULTS / "t3_slotF_replication_audit_20260515.md"

ORIGINAL = RESULTS / "lockbox_t3_slotF_cqr_width_conformal_20260515T100031Z.json"
REPLICATION = RESULTS / "lockbox_t3_slotF_cqr_width_conformal_20260515T121511Z_slotFrep_seed101.json"

PRIMARY_FRAC_GATE = 0.95
PRIMARY_MCID = 0.005


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def row_for(artifact: dict, cov_key: str) -> dict:
    row = artifact.get("results_per_coverage", {}).get(cov_key, {})
    return {
        "coverage": row.get("coverage"),
        "n_retained": row.get("n_retained"),
        "retained_ccc": row.get("iter47_retained_ccc"),
        "delta_retained_vs_full": row.get("delta_retained_vs_full"),
        "frac_retained_above_full": row.get("frac_retained_above_full"),
        "ci95": row.get("bootstrap_retained_ccc_ci95"),
        "passes_uncorrected_frac_gate": row.get("frac_retained_above_full", 0.0) >= PRIMARY_FRAC_GATE,
        "passes_mcid_005": row.get("delta_retained_vs_full", 0.0) >= PRIMARY_MCID,
        "artifact_verdict": artifact.get("verdicts_per_coverage", {}).get(cov_key),
    }


def main() -> None:
    original = load_json(ORIGINAL)
    replication = load_json(REPLICATION)

    coverage_rows = {}
    for cov_key in ("cov_70", "cov_50"):
        orig = row_for(original, cov_key)
        repl = row_for(replication, cov_key)
        coverage_rows[cov_key] = {
            "original": orig,
            "replication": repl,
            "same_retained_ccc": orig["retained_ccc"] == repl["retained_ccc"],
            "same_delta": orig["delta_retained_vs_full"] == repl["delta_retained_vs_full"],
            "replicated_gate_pass": (
                orig["passes_uncorrected_frac_gate"]
                and repl["passes_uncorrected_frac_gate"]
                and orig["passes_mcid_005"]
                and repl["passes_mcid_005"]
            ),
        }

    hard_failures = []
    if not original.get("sanity_y_nan_passes"):
        hard_failures.append("Original Slot F y-nan sanity did not pass.")
    if not replication.get("sanity_y_nan_passes"):
        hard_failures.append("Replication Slot F y-nan sanity did not pass.")
    if replication.get("quantile_seed") == original.get("quantile_seed", 42):
        hard_failures.append("Replication quantile seed is not disjoint from the original seed.")

    any_replicated_gate_pass = any(row["replicated_gate_pass"] for row in coverage_rows.values())
    decision = (
        "slotF_replication_promoted_deployable_secondary"
        if any_replicated_gate_pass and not hard_failures
        else "slotF_replication_boundary_lift_not_promoted"
    )

    report = {
        "name": "t3_slotF_replication_audit",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "script": Path(__file__).name,
        "not_a_model_result": True,
        "goal_complete": False,
        "original_artifact": str(ORIGINAL.relative_to(ROOT)),
        "replication_artifact": str(REPLICATION.relative_to(ROOT)),
        "replication_seed": replication.get("quantile_seed"),
        "original_seed": original.get("quantile_seed", 42),
        "bootstrap_seed": replication.get("bootstrap_seed"),
        "gates": {
            "replicated_uncorrected_frac_gate": PRIMARY_FRAC_GATE,
            "replicated_mcid": PRIMARY_MCID,
            "requires_both_original_and_replication": True,
        },
        "coverage_rows": coverage_rows,
        "hard_failures": hard_failures,
        "decision": decision,
        "passed": not hard_failures,
        "claim": (
            "Slot F remains a useful T3 deployable-secondary boundary-lift "
            "result, but it is not promoted under the replicated-uncorrected "
            "gate because neither retained coverage clears frac>full >= 0.95 "
            "in both original and seed-101 replication artifacts."
        ),
    }

    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n")

    lines = [
        "# T3 Slot F Replication Audit",
        "",
        f"- Decision: `{decision}`",
        f"- Passed: `{report['passed']}`",
        f"- Goal complete: `{report['goal_complete']}`",
        f"- Original: `{report['original_artifact']}`",
        f"- Replication: `{report['replication_artifact']}`",
        f"- Seeds: original `{report['original_seed']}`, replication `{report['replication_seed']}`",
        "",
        "| Coverage | Original CCC | Original frac>full | Rep CCC | Rep frac>full | Replicated gate pass |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for cov_key, row in coverage_rows.items():
        lines.append(
            "| {cov} | {occ} | {ofrac} | {rcc} | {rfrac} | `{gate}` |".format(
                cov=cov_key,
                occ=row["original"]["retained_ccc"],
                ofrac=row["original"]["frac_retained_above_full"],
                rcc=row["replication"]["retained_ccc"],
                rfrac=row["replication"]["frac_retained_above_full"],
                gate=row["replicated_gate_pass"],
            )
        )
    lines.extend(["", report["claim"], ""])
    OUT_MD.write_text("\n".join(lines))

    print(json.dumps({
        "passed": report["passed"],
        "decision": decision,
        "any_replicated_gate_pass": any_replicated_gate_pass,
        "hard_failures": len(hard_failures),
    }, indent=2))


if __name__ == "__main__":
    main()
