"""Audit iter34 auxiliary-label exposure under random RegressorChain orders.

This is a bug-impact / claim-label audit, not a new T1 model family.

The iter48 valid-range audit found that the locked iter34 T1 candidate used an
invalid auxiliary item-15 total for NLS036 (raw 9/9 -> top-level 18, valid total
range 0-8). A tempting argument is that item 15 is downstream of the T1 items
9-14 and therefore cannot affect the T1 sum. That argument is false for iter34:
the implementation uses ``RegressorChain(order="random", random_state=seed)``.

Modes:
  order   - static deterministic chain-order audit only.
  screen  - order audit plus all-base 5-fold stale-vs-valid impact screen.

The screen deliberately runs only the locked all-base iter34 architecture in
5-fold mode. It does not explore base subsets, does not write a preregistration,
does not run LOOCV, and cannot update a headline.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.multioutput import RegressorChain

from inductive_lib import ccc as ccc_fn
from project_paths import RESULTS_DIR, ensure_dir
from run_t1_iter4 import (
    PER_ITEM_CACHE,
    T1_ITEMS,
    V2_FEATURES,
    is_pd,
    v2_feature_columns,
)
from run_t1_iter33b_8item_chain import AUX_ITEMS, T1_SUM_ITEMS
from run_t1_iter34_hybrid_8item_multibase import BASE_LEARNERS
from run_t1_iter34_leakage_audit import run_5fold
from updrs_columns import UPDRS_PART3_ITEM_TOTAL_MAX, valid_updrs_item_total


ITER34_LOCKBOX_SEEDS = (42, 1337, 7)
ITER46_DECOMP_SEEDS = (42, 1337, 7, 2026, 9001)
ITEM_ORDER_COLUMNS = list(T1_SUM_ITEMS) + list(AUX_ITEMS)
INVALID_AUX_SID = "NLS036"
INVALID_AUX_ITEM = 15


def _finite_float(value: Any) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return x if np.isfinite(x) else float("nan")


def _item_value(raw_scores: dict[str, Any], item: int, *, validated: bool) -> float:
    if str(item) not in raw_scores:
        return float("nan")
    value = raw_scores[str(item)]
    if validated:
        valid_value = valid_updrs_item_total(item, value)
        return float(valid_value) if valid_value is not None else float("nan")
    return _finite_float(value)


def _load_aux_cohort(*, validated: bool) -> dict[str, Any]:
    """Load the iter34 T1+auxiliary cohort with stale or valid-range labels."""
    df = pd.read_csv(V2_FEATURES)
    feat_cols = v2_feature_columns(df)
    with open(PER_ITEM_CACHE, "r", encoding="utf-8") as f:
        raw = json.load(f)

    sids: list[str] = []
    feats: list[np.ndarray] = []
    hy: list[float] = []
    item_rows: dict[int, list[float]] = {item: [] for item in ITEM_ORDER_COLUMNS}
    for _, row in df.iterrows():
        sid = str(row["sid"])
        if not is_pd(sid) or sid not in raw:
            continue
        values = {
            item: _item_value(raw[sid], item, validated=validated)
            for item in ITEM_ORDER_COLUMNS
        }
        if not all(np.isfinite(values[item]) for item in ITEM_ORDER_COLUMNS):
            continue
        sids.append(sid)
        feats.append(row[feat_cols].to_numpy(dtype=np.float64))
        hy.append(_finite_float(row.get("hy", np.nan)))
        for item in ITEM_ORDER_COLUMNS:
            item_rows[item].append(values[item])

    items = {item: np.asarray(vals, dtype=np.float64) for item, vals in item_rows.items()}
    y_t1 = np.sum([items[item] for item in T1_ITEMS], axis=0)
    return {
        "label_scope": "validated_item_totals" if validated else "stale_unvalidated_item_totals",
        "sids": np.asarray(sids),
        "X": np.vstack(feats),
        "y_t1": y_t1,
        "hy": np.asarray(hy, dtype=np.float64),
        "items": items,
        "item_order": ITEM_ORDER_COLUMNS,
        "feat_cols_n": len(feat_cols),
    }


def _random_chain_order(seed: int) -> list[int]:
    """Return actual target-item order used by sklearn RegressorChain random mode."""
    rng_x = np.random.RandomState(0)
    rng_y = np.random.RandomState(1)
    X = rng_x.normal(size=(24, 4))
    Y = rng_y.normal(size=(24, len(ITEM_ORDER_COLUMNS)))
    base = ExtraTreesRegressor(n_estimators=1, random_state=seed, n_jobs=1)
    chain = RegressorChain(base, order="random", random_state=seed)
    chain.fit(X, Y)
    return [int(ITEM_ORDER_COLUMNS[idx]) for idx in chain.order_]


def _order_audit() -> dict[str, Any]:
    rows = []
    for seed in sorted(set(ITER34_LOCKBOX_SEEDS + ITER46_DECOMP_SEEDS)):
        order = _random_chain_order(seed)
        pos = {item: order.index(item) for item in order}
        t1_after_item15 = [item for item in T1_SUM_ITEMS if pos[item] > pos[INVALID_AUX_ITEM]]
        aux_before_t1 = {
            str(aux): [item for item in T1_SUM_ITEMS if pos[item] > pos[aux]]
            for aux in AUX_ITEMS
        }
        rows.append(
            {
                "seed": int(seed),
                "chain_order": order,
                "item15_position": int(pos[INVALID_AUX_ITEM]),
                "t1_items_after_item15": [int(item) for item in t1_after_item15],
                "n_t1_items_after_item15": int(len(t1_after_item15)),
                "aux_before_t1_items": aux_before_t1,
                "iter34_lockbox_seed": bool(seed in ITER34_LOCKBOX_SEEDS),
                "iter46_decomp_seed": bool(seed in ITER46_DECOMP_SEEDS),
            }
        )
    lockbox_rows = [row for row in rows if row["iter34_lockbox_seed"]]
    decomp_rows = [row for row in rows if row["iter46_decomp_seed"]]
    return {
        "item_columns_supplied_to_chain": ITEM_ORDER_COLUMNS,
        "implementation": {
            "script": "run_t1_iter34_hybrid_8item_multibase.py",
            "call": 'RegressorChain(regr, order="random", random_state=seed)',
            "important_correction": (
                "The supplied item column order is not the causal chain order. "
                "sklearn permutes the target order deterministically by seed."
            ),
        },
        "rows": rows,
        "summary": {
            "iter34_lockbox_seeds": list(ITER34_LOCKBOX_SEEDS),
            "iter34_lockbox_seeds_with_item15_upstream_of_any_t1": [
                int(row["seed"]) for row in lockbox_rows if row["n_t1_items_after_item15"] > 0
            ],
            "iter34_lockbox_seed_count_with_exposure": int(
                sum(row["n_t1_items_after_item15"] > 0 for row in lockbox_rows)
            ),
            "iter34_lockbox_seed_count": len(lockbox_rows),
            "iter46_decomp_seed_count_with_exposure": int(
                sum(row["n_t1_items_after_item15"] > 0 for row in decomp_rows)
            ),
            "iter46_decomp_seed_count": len(decomp_rows),
            "kimi_fixed_order_assumption_status": "falsified_by_code",
        },
    }


def _metrics(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    return {
        "ccc": float(ccc_fn(y, p)),
        "mae": float(np.mean(np.abs(y - p))),
        "pred_mean": float(np.mean(p)),
        "pred_std": float(np.std(p)),
        "true_mean": float(np.mean(y)),
        "true_std": float(np.std(y)),
    }


def _bootstrap_delta(y: np.ndarray, p_new: np.ndarray, p_ref: np.ndarray) -> dict[str, float | int]:
    rng = np.random.default_rng(20260509)
    n = len(y)
    deltas = np.empty(5000, dtype=np.float64)
    for i in range(len(deltas)):
        idx = rng.integers(0, n, size=n)
        deltas[i] = ccc_fn(y[idx], p_new[idx]) - ccc_fn(y[idx], p_ref[idx])
    return {
        "n_boot": int(len(deltas)),
        "delta_mean": float(np.mean(deltas)),
        "ci_low": float(np.quantile(deltas, 0.025)),
        "ci_high": float(np.quantile(deltas, 0.975)),
        "frac_above_zero": float(np.mean(deltas > 0)),
        "frac_abs_ge_0_025": float(np.mean(np.abs(deltas) >= 0.025)),
    }


def _run_scope(cohort: dict[str, Any], seeds: tuple[int, ...], n_workers: int) -> dict[str, Any]:
    sids = cohort["sids"]
    items_arr = np.column_stack([cohort["items"][item] for item in cohort["item_order"]])
    per_seed = []
    preds = []
    for seed in seeds:
        y_eff, pred = run_5fold(
            cohort["X"],
            cohort["y_t1"],
            cohort["hy"],
            items_arr,
            cohort["item_order"],
            sids,
            seed=seed,
            n_workers=n_workers,
        )
        if not np.array_equal(y_eff, cohort["y_t1"]):
            raise RuntimeError("unexpected y permutation in all-base screen")
        per_seed.append({"seed": int(seed), **_metrics(cohort["y_t1"], pred)})
        preds.append(pred)
    mean_pred = np.mean(np.column_stack(preds), axis=1)
    return {
        "label_scope": cohort["label_scope"],
        "n": int(len(sids)),
        "sids": [str(sid) for sid in sids],
        "per_seed": per_seed,
        "mean_prediction_metrics": _metrics(cohort["y_t1"], mean_pred),
        "seed_ccc_mean": float(np.mean([row["ccc"] for row in per_seed])),
        "seed_ccc_std": float(np.std([row["ccc"] for row in per_seed])),
        "mean_pred": mean_pred.tolist(),
        "y_true": cohort["y_t1"].tolist(),
    }


def _screen(validated: dict[str, Any], stale: dict[str, Any], *, seeds: tuple[int, ...], n_workers: int) -> dict[str, Any]:
    stale_result = _run_scope(stale, seeds, n_workers)
    valid_result = _run_scope(validated, seeds, n_workers)

    stale_by_sid = dict(zip(stale_result["sids"], stale_result["mean_pred"]))
    common_sids = [sid for sid in valid_result["sids"] if sid in stale_by_sid]
    y_common = np.asarray(valid_result["y_true"], dtype=np.float64)
    p_valid = np.asarray(valid_result["mean_pred"], dtype=np.float64)
    p_stale_common = np.asarray([stale_by_sid[sid] for sid in common_sids], dtype=np.float64)
    if common_sids != valid_result["sids"]:
        raise RuntimeError("validated SIDs are not the expected stale-subset order")

    valid_common_metrics = _metrics(y_common, p_valid)
    stale_common_metrics = _metrics(y_common, p_stale_common)
    delta_valid_minus_stale = valid_common_metrics["ccc"] - stale_common_metrics["ccc"]

    return {
        "scope": "all_base_iter34_5fold_stale_vs_valid_auxiliary_screen",
        "status": "screen_only_no_prereg_no_loocv_no_canonical_update",
        "seeds": list(seeds),
        "bases": list(BASE_LEARNERS),
        "n_workers": int(n_workers),
        "stale_unvalidated": {
            key: val for key, val in stale_result.items() if key not in {"mean_pred", "y_true"}
        },
        "validated": {
            key: val for key, val in valid_result.items() if key not in {"mean_pred", "y_true"}
        },
        "common_sid_comparison": {
            "n_common": int(len(common_sids)),
            "excluded_from_validated": sorted(set(stale_result["sids"]) - set(common_sids)),
            "validated_metrics_on_common": valid_common_metrics,
            "stale_trained_metrics_on_common_sids": stale_common_metrics,
            "delta_valid_minus_stale_common_ccc": float(delta_valid_minus_stale),
            "paired_bootstrap_delta_valid_minus_stale_common_ccc": _bootstrap_delta(
                y_common, p_valid, p_stale_common
            ),
            "materiality_threshold_abs_delta_ccc": 0.025,
            "materiality_flag": bool(abs(delta_valid_minus_stale) >= 0.025),
        },
    }


def _write_markdown(payload: dict[str, Any], path: Path) -> None:
    order = payload["order_audit"]
    lines = [
        "# T1 Iter34 Auxiliary Chain-Order Audit",
        "",
        f"Created: `{payload['created_at_utc']}`",
        "",
        "## Verdict",
        "",
        (
            "The fixed-column-order argument is false for iter34 because "
            "`RegressorChain(order=\"random\")` permutes targets by seed. "
            "The invalid item-15 auxiliary label can be upstream of T1 item "
            "predictions in some locked seeds."
        ),
        "",
        "## Chain Orders",
        "",
        "| Seed | Chain order | T1 items after item 15 | Iter34 lockbox seed |",
        "|---:|---|---|---|",
    ]
    for row in order["rows"]:
        lines.append(
            "| {seed} | `{chain}` | `{after}` | {lockbox} |".format(
                seed=row["seed"],
                chain=row["chain_order"],
                after=row["t1_items_after_item15"],
                lockbox=row["iter34_lockbox_seed"],
            )
        )
    lines.extend(
        [
            "",
            "## Scope",
            "",
            "- This is a methodology/claim-label audit.",
            "- It does not create a new T1 model family.",
            "- It does not pre-register or run LOOCV.",
            "- It does not update canonical T1.",
        ]
    )
    if "impact_screen" in payload:
        cmp_block = payload["impact_screen"]["common_sid_comparison"]
        lines.extend(
            [
                "",
                "## All-Base 5-Fold Impact Screen",
                "",
                f"- Status: `{payload['impact_screen']['status']}`",
                f"- Common N: `{cmp_block['n_common']}`",
                f"- Excluded from validated cohort: `{cmp_block['excluded_from_validated']}`",
                (
                    "- Delta validated-minus-stale common CCC: "
                    f"`{cmp_block['delta_valid_minus_stale_common_ccc']:+.4f}`"
                ),
                (
                    "- Materiality flag at |delta| >= 0.025: "
                    f"`{cmp_block['materiality_flag']}`"
                ),
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["order", "screen"], default="order")
    parser.add_argument("--seeds", nargs="*", type=int, default=list(ITER46_DECOMP_SEEDS))
    parser.add_argument("--n_workers", type=int, default=11)
    args = parser.parse_args()

    ensure_dir(RESULTS_DIR)
    payload: dict[str, Any] = {
        "audit": "t1_iter34_auxiliary_random_chain_order",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "mode": args.mode,
        "invalid_auxiliary_label": {
            "sid": INVALID_AUX_SID,
            "item": INVALID_AUX_ITEM,
            "stale_top_level_value": 18.0,
            "valid_total_range": [0.0, float(UPDRS_PART3_ITEM_TOTAL_MAX[INVALID_AUX_ITEM])],
            "source": "results/t1_iter48_aux_validrange_audit.json",
        },
        "order_audit": _order_audit(),
        "decision_boundary": (
            "Order exposure means the invalid auxiliary label is not structurally "
            "irrelevant. Any impact screen is claim-label evidence only; no "
            "post-hoc LOOCV or canonical promotion is allowed."
        ),
        "web_source": {
            "mds_updrs_part_iii_items_scored_0_to_4": (
                "https://www.apta.org/patient-care/evidence-based-practice-resources/"
                "test-measures/unified-parkinsons-disease-rating-scale-updrs-"
                "movement-disorders-society-mds-modified-unified-parkinsons-"
                "disease-rating-scale-mds-updrs"
            )
        },
    }

    if args.mode == "screen":
        stale = _load_aux_cohort(validated=False)
        valid = _load_aux_cohort(validated=True)
        payload["cohorts"] = {
            "stale_n": int(len(stale["sids"])),
            "validated_n": int(len(valid["sids"])),
            "validated_excludes": sorted(set(stale["sids"]) - set(valid["sids"])),
            "feat_cols_n": int(valid["feat_cols_n"]),
        }
        payload["impact_screen"] = _screen(
            valid,
            stale,
            seeds=tuple(args.seeds),
            n_workers=args.n_workers,
        )

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_json = RESULTS_DIR / f"t1_iter34_aux_order_audit_{ts}.json"
    out_md = RESULTS_DIR / f"t1_iter34_aux_order_audit_{ts}.md"
    stable_json = RESULTS_DIR / "t1_iter34_aux_order_audit.json"
    stable_md = RESULTS_DIR / "t1_iter34_aux_order_audit.md"
    for path in (out_json, stable_json):
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    for path in (out_md, stable_md):
        _write_markdown(payload, path)
    print(f"Wrote {out_json}")
    print(f"Wrote {out_md}")
    print(f"Wrote {stable_json}")
    print(f"Wrote {stable_md}")
    print(json.dumps(payload["order_audit"]["summary"], indent=2))
    if "impact_screen" in payload:
        print(json.dumps(payload["impact_screen"]["common_sid_comparison"], indent=2))


if __name__ == "__main__":
    main()
