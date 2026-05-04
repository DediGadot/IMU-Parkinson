"""LOOCV lockbox for interaction-screen winners.

Pre-registers a (item, variant) pair and runs LOOCV with 3 seeds, saving the
mean OOF as .npy alongside the JSON metrics.

Usage:
  python run_interaction_lockbox.py --item 12 --variant v2_plus_interactions \
      --tag interaction_lockbox

The pre-registration is timestamped at start and emits a separate JSON which
the agent SHOULD NOT modify after the run.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import full_metrics
from project_paths import RESULTS_DIR, ensure_dir
from run_t1_iter4 import SEEDS
from run_interaction_screen import (
    VARIANTS, load_data, _filter_nan,
    run_5null_gate, run_one,
)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--item", type=int, required=True)
    p.add_argument("--variant", type=str, required=True)
    p.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS))
    p.add_argument("--tag", type=str, default="interaction_lockbox")
    args = p.parse_args()

    if args.variant not in VARIANTS:
        raise SystemExit(f"unknown variant {args.variant}; available: {sorted(VARIANTS.keys())}")

    out_dir = RESULTS_DIR
    ensure_dir(out_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Step 1: emit pre-registration
    prereg = {
        "timestamp": timestamp,
        "item": args.item,
        "variant": args.variant,
        "eval": "loocv",
        "seeds": list(args.seeds),
        "n_subjects": 0,  # filled after data load
        "rationale": "Interaction features + self-normalisation; 5-fold winner pre-registered for LOOCV.",
        "git_status": "post-interaction-screen",
    }
    prereg_path = out_dir / f"preregistration_interaction_{args.item}_{args.variant}_{timestamp}.json"

    print(f"[lockbox] Loading data...", flush=True)
    d = load_data()
    d_f, y = _filter_nan(d, args.item)
    prereg["n_subjects"] = int(len(y))
    with open(prereg_path, "w") as f:
        json.dump(prereg, f, indent=2)
    print(f"[lockbox] Pre-registered → {prereg_path}", flush=True)
    print(f"[lockbox] Running LOOCV: item={args.item} variant={args.variant} N={len(y)} seeds={args.seeds}",
          flush=True)
    t0 = time.time()
    result = run_one(d_f, args.item, args.variant, "loocv",
                    seeds=tuple(args.seeds), with_null=False)
    elapsed = time.time() - t0
    print(f"[lockbox] Done in {elapsed:.1f}s. CCC={result.get('ccc_mean'):.4f}", flush=True)

    # Save OOF + JSON
    oof_path = out_dir / f"lockbox_interaction_{args.item}_{args.variant}_{timestamp}.oof.npy"
    if "_oof_array" in result:
        np.save(oof_path, np.asarray(result["_oof_array"], dtype=np.float64))
        print(f"[lockbox] Saved OOF → {oof_path}", flush=True)
    json_path = out_dir / f"lockbox_interaction_{args.item}_{args.variant}_{timestamp}.json"
    result_clean = {k: v for k, v in result.items() if k != "_oof_array"}
    result_clean["preregistration_path"] = str(prereg_path)
    with open(json_path, "w") as f:
        json.dump(result_clean, f, indent=2, default=float)
    print(f"[lockbox] Saved JSON → {json_path}", flush=True)


if __name__ == "__main__":
    main()
