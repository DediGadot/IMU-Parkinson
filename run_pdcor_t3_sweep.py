"""Threshold + alpha sweep on T3 pdCor-selection stack to characterize the
borderline +0.047 ΔCCC result and find the most-defensible operating point."""
from __future__ import annotations
import json
import subprocess
import sys
from itertools import product
from pathlib import Path

CONFIGS = [
    # (threshold, max_k, alpha)
    (0.08, 100, 10),
    (0.10, 50, 10),
    (0.10, 50, 30),
    (0.10, 30, 30),
    (0.10, 30, 100),
    (0.15, 50, 30),
    (0.15, 30, 30),
    (0.20, 30, 30),
    (0.20, 30, 100),
]

results = []
for thr, k, a in CONFIGS:
    print(f"\n=== threshold={thr} max_k={k} alpha={a} ===", flush=True)
    cmd = [
        sys.executable, "run_pdcor_selection_stack.py",
        "--target", "t3",
        "--threshold", str(thr),
        "--max-k", str(k),
        "--alpha", str(a),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(p.stdout)
    if p.returncode != 0:
        sys.stderr.write(p.stderr)
        continue
    # Find the latest result file
    files = sorted(Path("results").glob(f"metric_pdcor_selection_t3_thr{int(thr*100):03d}_k{k}_*.json"))
    if files:
        d = json.loads(files[-1].read_text())
        results.append({
            "threshold": thr,
            "max_k": k,
            "alpha": a,
            "ccc": d["stacked"]["ccc"],
            "delta_ccc": d["delta_ccc"],
            "frac_pos": d["delta_ccc_bootstrap_frac_positive"],
            "ci_lo": d["delta_ccc_bootstrap_ci_lower"],
            "ci_hi": d["delta_ccc_bootstrap_ci_upper"],
            "selected_mean": d["selected_count_mean"],
        })

print("\n\n=== SUMMARY ===")
import pandas as pd
df = pd.DataFrame(results)
print(df.to_string(index=False))
df.to_csv("results/pdcor_t3_threshold_sweep.csv", index=False)
print("\n→ wrote results/pdcor_t3_threshold_sweep.csv")
