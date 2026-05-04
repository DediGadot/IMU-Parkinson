"""Cache L/R asymmetry features (`diff` and `abs_diff` for paired (L_, R_) features).

Pure post-processing of `results/ablation_v3_features.csv` — no raw data needed.

For every column pair (`L_<X>`, `R_<X>`) in the v2 cache:
  - `LR_diff_<X>`     = L_<X> - R_<X>     (signed; preserves dominance direction)
  - `LR_abs_diff_<X>` = |L_<X> - R_<X>|   (unsigned; preserves magnitude regardless of side)

Output: `results/lr_asymmetry_features.csv` with columns: sid + new asymmetry features.

CLI fix from codex: asymmetry cancels unless symptom dominance is aligned across subjects.
Therefore we ship BOTH variants (signed + unsigned). Tree models pick which to use per fold.

Usage:
  uv run python cache_lr_asymmetry.py
  python3 cache_lr_asymmetry.py --smoke   # smoke test on 5 rows
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from project_paths import RESULTS_DIR, ensure_dir

V2_FEATURES = RESULTS_DIR / "ablation_v3_features.csv"
OUT_PATH = RESULTS_DIR / "lr_asymmetry_features.csv"


def find_paired_columns(columns: list[str]) -> list[tuple[str, str, str]]:
    """Find (L_<X>, R_<X>, <X>) triples in the v2 columns.

    Pairing only on prefix (`L_`/`R_`); otherwise the suffix must match exactly.
    """
    l_cols = {c[2:]: c for c in columns if c.startswith("L_")}
    r_cols = {c[2:]: c for c in columns if c.startswith("R_")}
    common_suffixes = sorted(set(l_cols) & set(r_cols))
    return [(l_cols[s], r_cols[s], s) for s in common_suffixes]


def build_asymmetry_frame(v2_df: pd.DataFrame) -> pd.DataFrame:
    pairs = find_paired_columns(list(v2_df.columns))
    if not pairs:
        raise RuntimeError("No (L_, R_) paired columns found in v2 cache")
    out = {"sid": v2_df["sid"].values}
    for l_col, r_col, suffix in pairs:
        l = v2_df[l_col].astype(np.float32).values
        r = v2_df[r_col].astype(np.float32).values
        out[f"LR_diff_{suffix}"] = l - r
        out[f"LR_abs_diff_{suffix}"] = np.abs(l - r)
    return pd.DataFrame(out)


def run_smoke_check(asym_df: pd.DataFrame) -> None:
    n_pairs = (len(asym_df.columns) - 1) // 2
    if n_pairs < 100:
        raise RuntimeError(f"Too few pairs: {n_pairs} (expect ≥500)")
    diff_cols = [c for c in asym_df.columns if c.startswith("LR_diff_")]
    abs_cols = [c for c in asym_df.columns if c.startswith("LR_abs_diff_")]
    if len(diff_cols) != len(abs_cols):
        raise RuntimeError(f"Mismatch: {len(diff_cols)} diff vs {len(abs_cols)} abs_diff")
    abs_block = asym_df[abs_cols].values
    if (abs_block < 0).any():
        raise RuntimeError("abs_diff has negative values — sanity broken")
    nz_frac = float((np.abs(asym_df[diff_cols].values) > 1e-9).mean())
    if nz_frac < 0.5:
        raise RuntimeError(f"Most diff features are zero ({nz_frac:.2%}) — likely all sensors identical")
    print(f"  smoke OK: {n_pairs} pairs, abs_diff non-negative, diff non-zero fraction={nz_frac:.2%}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true",
                    help="run on first 5 subjects only as sanity check")
    ap.add_argument("--out", default=str(OUT_PATH))
    args = ap.parse_args()

    ensure_dir(RESULTS_DIR)
    v2_df = pd.read_csv(V2_FEATURES)
    if args.smoke:
        v2_df = v2_df.head(5)
    print(f"Loaded {len(v2_df)} subjects, {len(v2_df.columns)} v2 columns from {V2_FEATURES}")

    asym_df = build_asymmetry_frame(v2_df)
    run_smoke_check(asym_df)

    out_path = Path(args.out)
    asym_df.to_csv(out_path, index=False)
    print(f"Wrote {asym_df.shape[0]} rows × {asym_df.shape[1]} cols → {out_path}")


if __name__ == "__main__":
    main()
