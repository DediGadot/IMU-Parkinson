"""Build a per-subject self-normalised version of the V2 feature matrix.

Hypothesis: each subject has an idiosyncratic baseline (anatomy, sensor mounting,
walking style) that adds noise to inter-subject comparison. By subtracting the
per-subject median across HOMOLOGOUS features (same metric, different sensor) we
remove that baseline while preserving relative differences across sensors.

Each V2 column has the form `<sensor>_<metric>`. We group columns by `<metric>`
and, for every subject, compute the median across the sensor axis within that
group. Each column's self-normalised value = original − per-subject group median.

This is data-only (no target involvement) so the cache can be precomputed once.

Output: results/v2_self_normalized.csv (sid + selfnorm_<original col name>)
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from run_t1_iter4 import load_pd_data, v2_feature_columns, V2_FEATURES

OUT_PATH = REPO_ROOT / "results" / "v2_self_normalized.csv"

SENSOR_PREFIXES = (
    "Forehead", "Sternum", "Lumbar", "LowerBack", "Xiphoid",
    "L_Ankle", "R_Ankle", "L_Wrist", "R_Wrist",
    "L_Foot", "R_Foot", "L_Hand", "R_Hand",
)


def _split_sensor_metric(col: str) -> tuple[str, str] | None:
    for sn in SENSOR_PREFIXES:
        if col.startswith(sn + "_"):
            return sn, col[len(sn) + 1:]
    return None


def main() -> None:
    print(f"[selfnorm] Loading {V2_FEATURES}", flush=True)
    d = load_pd_data()
    feat_cols = d["feat_cols"]
    X = d["X_v2"].copy()  # (n, p)
    sids = list(d["sids"])
    n, p = X.shape
    print(f"[selfnorm] N={n} PD subjects, p={p} V2 features", flush=True)

    # Group features by metric (post-sensor suffix)
    metric_to_idx: dict[str, list[int]] = defaultdict(list)
    n_no_sensor = 0
    for j, col in enumerate(feat_cols):
        parsed = _split_sensor_metric(col)
        if parsed is None:
            n_no_sensor += 1
            continue
        _, metric = parsed
        metric_to_idx[metric].append(j)
    n_groups = len(metric_to_idx)
    n_grouped = sum(len(v) for v in metric_to_idx.values())
    print(f"[selfnorm] {n_grouped} cols in {n_groups} sensor groups; {n_no_sensor} cols have no sensor prefix",
          flush=True)

    # For each subject and each group, compute median across sensor axis
    # then subtract from each member column.
    X_sn = np.zeros_like(X)
    for metric, idxs in metric_to_idx.items():
        if len(idxs) < 2:
            # Singleton: self-normalisation is meaningless (becomes zero). Keep raw value as fallback.
            X_sn[:, idxs] = X[:, idxs]
            continue
        sub = X[:, idxs]  # (n, k)
        # nanmedian across the sensor axis (per row)
        med = np.nanmedian(sub, axis=1, keepdims=True)
        med = np.where(np.isnan(med), 0.0, med)
        X_sn[:, idxs] = sub - med
    # Cols without sensor prefix: keep raw (these are e.g. dv_*, ix_*, ev_*, cv_* — not anatomic)
    # Identify them
    grouped_set: set[int] = set()
    for v in metric_to_idx.values():
        grouped_set.update(v)
    for j in range(p):
        if j not in grouped_set:
            X_sn[:, j] = X[:, j]

    out_cols = [f"selfnorm_{c}" for c in feat_cols]
    df_out = pd.DataFrame(X_sn, columns=out_cols)
    df_out.insert(0, "sid", sids)
    df_out.to_csv(OUT_PATH, index=False)
    nan_ratio = df_out.iloc[:, 1:].isna().mean().mean()
    print(f"[selfnorm] Wrote {OUT_PATH}", flush=True)
    print(f"[selfnorm] N={len(df_out)}, p={len(out_cols)}, mean NaN ratio={nan_ratio:.4f}", flush=True)


if __name__ == "__main__":
    main()
