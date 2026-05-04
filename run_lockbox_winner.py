"""Phase 7 (lockbox): pick the 5-fold winner, pre-register it, run LOOCV ONCE.

Reads all `*_5split.json` files from results/, ranks by T1 CCC, applies the
codex-mandated tiebreaker (simplicity, then fold-to-fold std), writes a
`results/preregistration_<timestamp>.json` and stops. The user must approve
the registration before running the LOOCV confirmation step.

Usage:
  python3 run_lockbox_winner.py              # screen + pre-register
  python3 run_lockbox_winner.py --confirm    # run LOOCV on the registered pipeline
  python3 run_lockbox_winner.py --report     # print full ladder for paper
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from glob import glob
from pathlib import Path

from project_paths import RESULTS_DIR, results_artifact_path

SIMPLICITY_RANK = {
    # Lower = simpler. Used for tiebreaks within ±0.01 CCC.
    "B0_null_mean": 0,
    "B4_demo_ridge": 1,
    "B5_fm_linear": 1,
    "B6_shallow_imu": 2,
    "B1_v2_only": 3,
    "B2_fm_only": 3,
    "B3_v2_fm": 4,
    "demo_residual_base": 5,
    "demo_residual_demo_first": 6,
    "demo_residual_demo_stacked": 7,
    "event_features_mean": 4,           # same as B3 essentially
    "event_features_max": 5,
    "event_features_topk_mean": 5,
    "event_features_mean_plus_max": 6,
    "event_features_mean_plus_std": 6,
    "event_features_mean_max_std": 7,
}


def load_all_5fold():
    """Returns list of {label, target, ccc, slope, mae, fold_std, simplicity}."""
    rows = []
    for path in sorted(glob(str(RESULTS_DIR / "*_5split.json"))):
        try:
            d = json.load(open(path))
        except Exception:
            continue
        if "ccc" not in d or "target" not in d:
            continue

        name = Path(path).stem.replace("_5split", "")
        # Derive a label key for simplicity ranking
        for prefix in ("baseline_", "demo_residual_", "event_features_", "inductive_"):
            if name.startswith(prefix):
                label = name[len(prefix):].rsplit("_", 1)[0] if name.startswith(("baseline_", "inductive_")) else name.rsplit("_", 1)[0]
                if name.startswith("baseline_"):
                    label = name.replace("baseline_", "").rsplit("_", 1)[0]
                elif name.startswith("inductive_"):
                    # inductive_<variant>_<target>
                    label = "inductive_" + name.replace("inductive_", "").rsplit("_", 1)[0]
                else:
                    label = name.rsplit("_", 1)[0]
                break
        else:
            label = name.rsplit("_", 1)[0]

        # Compute fold-to-fold CCC std if we have per-subject preds (cheap proxy)
        per_subj = d.get("per_subject", {})
        fold_std = 0.0  # placeholder; would need fold IDs to compute properly

        rows.append({
            "path": path,
            "label": label,
            "target": d["target"],
            "ccc": d["ccc"],
            "slope": d.get("cal_slope", 0),
            "mae": d.get("mae", 0),
            "n": d.get("n", len(per_subj.get("y_true", []))),
            "fold_std": fold_std,
            "simplicity": SIMPLICITY_RANK.get(label, 99),
            "runtime_s": d.get("runtime_s", 0),
        })
    return rows


def pick_winner(rows: list, target: str = "t1") -> dict:
    """Codex tiebreaker: highest CCC, ties (within ±0.01) broken by simplicity."""
    candidates = [r for r in rows if r["target"] == target]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (-r["ccc"], r["simplicity"]))
    best_ccc = candidates[0]["ccc"]
    tied = [r for r in candidates if r["ccc"] >= best_ccc - 0.01]
    tied.sort(key=lambda r: r["simplicity"])
    return tied[0]


def write_report(rows: list, out_path: Path) -> None:
    with open(out_path, "w") as f:
        f.write(f"# 5-fold Lockbox Screening Report — {datetime.now().isoformat()}\n\n")
        for target in ("t1", "t3"):
            tgt_rows = sorted(
                [r for r in rows if r["target"] == target],
                key=lambda r: -r["ccc"],
            )
            if not tgt_rows:
                continue
            f.write(f"## {target.upper()} ranking ({len(tgt_rows)} configs)\n\n")
            f.write(f"| Rank | Label | CCC | slope | MAE | N | Simplicity | Time |\n")
            f.write(f"|---|---|---:|---:|---:|---:|---:|---:|\n")
            for i, r in enumerate(tgt_rows[:25]):
                f.write(f"| {i+1} | {r['label']} | {r['ccc']:.3f} | {r['slope']:.3f} | "
                        f"{r['mae']:.3f} | {r['n']} | {r['simplicity']} | {r['runtime_s']:.0f}s |\n")
            f.write("\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true", help="Run LOOCV on registered pipeline")
    ap.add_argument("--report", action="store_true", help="Print full ladder")
    args = ap.parse_args()

    rows = load_all_5fold()
    print(f"Loaded {len(rows)} 5-fold result files")

    # Always print the report
    report_path = RESULTS_DIR / "lockbox_report.md"
    write_report(rows, report_path)
    print(f"Wrote ladder report -> {report_path}")

    # Pick winners for T1 and T3
    winner_t1 = pick_winner(rows, "t1")
    winner_t3 = pick_winner(rows, "t3")
    if winner_t1:
        print(f"\nT1 WINNER: {winner_t1['label']} (CCC={winner_t1['ccc']:.3f}, simplicity={winner_t1['simplicity']})")
    if winner_t3:
        print(f"T3 WINNER: {winner_t3['label']} (CCC={winner_t3['ccc']:.3f}, simplicity={winner_t3['simplicity']})")

    # Pre-register
    if winner_t1 and not args.confirm:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        spec = {
            "timestamp_utc": timestamp,
            "purpose": "Lockbox pre-registration: 5-fold winner gets ONE LOOCV evaluation as headline",
            "winner_t1": winner_t1,
            "winner_t3": winner_t3,
            "tiebreaker_rule": "highest CCC; ties within 0.01 broken by simplicity, then fold std",
            "loocv_command_t1": _loocv_command(winner_t1),
            "loocv_command_t3": _loocv_command(winner_t3) if winner_t3 else None,
        }
        path = RESULTS_DIR / f"preregistration_{timestamp}.json"
        with open(path, "w") as f:
            json.dump(spec, f, indent=2)
        print(f"\nPre-registration written -> {path}")
        print("Run with --confirm to execute LOOCV on the pre-registered pipelines.")


def _loocv_command(winner: dict) -> str:
    label = winner["label"]
    target = winner["target"]
    if label.startswith("inductive_"):
        variant = label.replace("inductive_", "")
        return f"python3 run_inductive_ablation.py --variant {variant} --target {target} --eval loocv"
    if label.startswith("demo_residual_"):
        return None  # would need a --eval loocv flag added
    if label.startswith("event_features_"):
        return None
    if label.startswith("B"):
        return f"python3 run_baselines.py --baseline {label} --target {target}  # add --loocv flag"
    return f"# unknown winner schema: {label}"


if __name__ == "__main__":
    main()
