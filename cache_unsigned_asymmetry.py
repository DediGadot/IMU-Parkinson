"""cache_unsigned_asymmetry.py — Dominance-aligned unsigned asymmetry features.

Addresses gemini's specific proposal: signed L-R asymmetry cancels at the cohort
level when subjects' lateralised PD onset isn't aligned. Instead, take max(L,R)
(MOST-affected side) and min(L,R) (LEAST-affected side) — these encode
"how bad is the worse limb" and "how preserved is the better limb" without
requiring a-priori dominance alignment.

abs(L-R) was already in lr_asymmetry_features.csv and the failure log marks
that whole cache DEAD. The new contribution here is max/min separation.

Source: results/ablation_v3_features.csv (V2 cache).
Pairs found: 585 L/R-paired feature stems.
Derived features per pair: max(L,R), min(L,R) → 1170 total features.

Output: results/unsigned_asymmetry_features.csv.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
V2_FEATURES = REPO_ROOT / "results" / "ablation_v3_features.csv"
DEFAULT_OUTPUT = REPO_ROOT / "results" / "unsigned_asymmetry_features.csv"

# Two L/R paired-naming patterns observed in V2:
# 1) sensor-prefix:  L_Ankle_am_iqr  <-> R_Ankle_am_iqr
# 2) family-prefix:  fc_L_cad        <-> fc_R_cad   (foot contact, etc.)
SENSOR_PREFIX_RE = re.compile(r"^([LR])_([A-Z][A-Za-z]+)_(.+)$")
FAMILY_PREFIX_RE = re.compile(r"^(fc|pa|tg|nl|sv|fq|hr|ix|ext)_([LR])_(.+)$")


def _find_lr_pairs(cols: list[str]) -> list[tuple[str, str, str]]:
    """Return list of (left_col, right_col, derived_stem) tuples."""
    sensor_buckets: dict[tuple[str, str], dict[str, str]] = {}
    family_buckets: dict[tuple[str, str], dict[str, str]] = {}
    for c in cols:
        m1 = SENSOR_PREFIX_RE.match(c)
        if m1:
            side, sensor, suffix = m1.group(1), m1.group(2), m1.group(3)
            sensor_buckets.setdefault((sensor, suffix), {})[side] = c
            continue
        m2 = FAMILY_PREFIX_RE.match(c)
        if m2:
            family, side, suffix = m2.group(1), m2.group(2), m2.group(3)
            family_buckets.setdefault((family, suffix), {})[side] = c

    pairs: list[tuple[str, str, str]] = []
    for (sensor, suffix), sides in sensor_buckets.items():
        if "L" in sides and "R" in sides:
            stem = f"{sensor}_{suffix}"
            pairs.append((sides["L"], sides["R"], stem))
    for (family, suffix), sides in family_buckets.items():
        if "L" in sides and "R" in sides:
            stem = f"{family}_{suffix}"
            pairs.append((sides["L"], sides["R"], stem))
    return pairs


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--v2", default=str(V2_FEATURES))
    p.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = p.parse_args()

    df = pd.read_csv(args.v2)
    print(f"Loaded V2 features: shape={df.shape}", flush=True)

    pairs = _find_lr_pairs(list(df.columns))
    print(f"Found {len(pairs)} L/R-paired feature stems", flush=True)

    out_cols: dict[str, np.ndarray] = {"sid": df["sid"].to_numpy()}
    for left_col, right_col, stem in pairs:
        L = df[left_col].to_numpy(dtype=np.float64)
        R = df[right_col].to_numpy(dtype=np.float64)
        out_cols[f"unasym_max_{stem}"] = np.fmax(L, R)
        out_cols[f"unasym_min_{stem}"] = np.fmin(L, R)

    out = pd.DataFrame(out_cols)
    out.to_csv(args.output, index=False)
    n_subj, n_feat = out.shape[0], out.shape[1] - 1
    print(f"Wrote {args.output}", flush=True)
    print(f"  shape = ({n_subj} subjects, {n_feat} features)", flush=True)
    # Coverage diagnostic
    nan_pct = out.drop(columns=["sid"]).isna().mean(axis=0).describe(percentiles=[0.5, 0.9])
    print(f"  per-feature NaN-fraction:\n{nan_pct.to_string()}", flush=True)


if __name__ == "__main__":
    main()
