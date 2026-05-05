"""Fit learning curve to iter5 subsample CCC and project to N=150/200/300.

Fits two parametric models:
  (a) CCC(N) = a - b * N^(-c)  (Pareto-style decay; standard in learning-curve lit)
  (b) CCC(N) = a + b * log(N)  (log-linear; sometimes better at small N)

Picks the better fit by AIC, reports projection to N ∈ {120, 150, 200, 250, 300}
with bootstrap CI.

Usage:
  python3 fit_learning_curve.py --in results/learning_curve_iter5.csv
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit


def pareto_model(n: np.ndarray, a: float, b: float, c: float) -> np.ndarray:
    return a - b * np.power(n, -c)


def loglinear_model(n: np.ndarray, a: float, b: float) -> np.ndarray:
    return a + b * np.log(n)


def fit_with_bootstrap(df: pd.DataFrame, n_boot: int = 2000, seed: int = 42) -> dict:
    """Fit both models on the (n_pd, ccc) data; project; bootstrap CIs over jobs."""
    rng = np.random.RandomState(seed)
    grouped = df.groupby("n_pd")["ccc"]
    n_levels = sorted(grouped.groups)
    means = np.array([grouped.get_group(n).mean() for n in n_levels])
    stds = np.array([grouped.get_group(n).std() for n in n_levels])

    # Point fits
    try:
        popt_p, pcov_p = curve_fit(
            pareto_model, n_levels, means,
            p0=[0.6, 5.0, 0.5], bounds=([0, 0, 0.05], [1.0, 100, 2.0]), maxfev=10000,
        )
    except Exception as e:
        popt_p = [np.nan, np.nan, np.nan]; pcov_p = None
    popt_l, pcov_l = curve_fit(loglinear_model, n_levels, means, p0=[0.0, 0.1])

    # AIC
    yhat_p = pareto_model(np.array(n_levels), *popt_p) if not np.any(np.isnan(popt_p)) else np.full_like(means, np.nan)
    yhat_l = loglinear_model(np.array(n_levels), *popt_l)
    rss_p = float(np.nansum((means - yhat_p) ** 2))
    rss_l = float(np.sum((means - yhat_l) ** 2))
    n = len(n_levels)
    aic_p = n * np.log(rss_p / n + 1e-12) + 2 * 3
    aic_l = n * np.log(rss_l / n + 1e-12) + 2 * 2

    target_n = (89, 100, 120, 150, 200, 250, 300)

    # Bootstrap projection
    boot_proj = {n: {"pareto": [], "loglinear": []} for n in target_n}
    for _ in range(n_boot):
        # Resample within each n level (preserving group structure)
        boot_means = []
        for nl in n_levels:
            grp = grouped.get_group(nl).values
            samp = rng.choice(grp, size=len(grp), replace=True)
            boot_means.append(samp.mean())
        boot_means = np.array(boot_means)
        try:
            p_p, _ = curve_fit(pareto_model, n_levels, boot_means,
                               p0=[0.6, 5.0, 0.5], bounds=([0, 0, 0.05], [1.0, 100, 2.0]), maxfev=10000)
        except Exception:
            p_p = popt_p
        p_l, _ = curve_fit(loglinear_model, n_levels, boot_means, p0=[0.0, 0.1])
        for tn in target_n:
            boot_proj[tn]["pareto"].append(float(pareto_model(np.array([tn]), *p_p)[0]))
            boot_proj[tn]["loglinear"].append(float(loglinear_model(np.array([tn]), *p_l)[0]))

    projections = {}
    for tn in target_n:
        for model in ("pareto", "loglinear"):
            arr = np.array(boot_proj[tn][model])
            projections[f"{model}_n{tn}"] = dict(
                point=(float(pareto_model(np.array([tn]), *popt_p)[0]) if model == "pareto"
                       else float(loglinear_model(np.array([tn]), *popt_l)[0])),
                ci_low=float(np.percentile(arr, 2.5)),
                ci_high=float(np.percentile(arr, 97.5)),
            )

    return dict(
        n_levels=n_levels,
        ccc_means=means.tolist(),
        ccc_stds=stds.tolist(),
        pareto_params=dict(a=float(popt_p[0]), b=float(popt_p[1]), c=float(popt_p[2])),
        loglinear_params=dict(a=float(popt_l[0]), b=float(popt_l[1])),
        rss_pareto=rss_p, rss_loglinear=rss_l,
        aic_pareto=aic_p, aic_loglinear=aic_l,
        better_model="pareto" if aic_p < aic_l else "loglinear",
        projections=projections,
        n_boot=n_boot,
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="inp", default="results/learning_curve_iter5.csv")
    p.add_argument("--out", default="results/learning_curve_fit.json")
    args = p.parse_args()

    df = pd.read_csv(args.inp)
    print(f"Loaded {len(df)} jobs from {args.inp}")
    print(df.groupby("n_pd")["ccc"].agg(["mean", "std", "count"]))

    fit = fit_with_bootstrap(df, n_boot=2000)
    with open(args.out, "w") as f:
        json.dump(fit, f, indent=2)
    print(f"\nWrote {args.out}")

    print(f"\nBetter-fit model (lower AIC): {fit['better_model']}")
    print(f"  Pareto params: a={fit['pareto_params']['a']:.4f}, b={fit['pareto_params']['b']:.4f}, c={fit['pareto_params']['c']:.4f}")
    print(f"  Loglin params: a={fit['loglinear_params']['a']:.4f}, b={fit['loglinear_params']['b']:.4f}")
    print(f"  AIC: pareto={fit['aic_pareto']:.2f}  loglinear={fit['aic_loglinear']:.2f}")

    print(f"\nProjections (point [95% CI]):")
    print(f"{'N':>6}{'Pareto':>30}{'LogLinear':>30}")
    for tn in (89, 100, 120, 150, 200, 250, 300):
        p_ = fit['projections'][f'pareto_n{tn}']
        l_ = fit['projections'][f'loglinear_n{tn}']
        print(f"{tn:>6}  {p_['point']:.4f} [{p_['ci_low']:.4f},{p_['ci_high']:.4f}]"
              f"   {l_['point']:.4f} [{l_['ci_low']:.4f},{l_['ci_high']:.4f}]")

    # Lift over canonical iter5 0.5227 at N=98
    print(f"\nProjected lift over canonical iter5 (N=98 CCC=0.5227):")
    print(f"{'N':>6}{'Δ Pareto (best)':>26}")
    for tn in (120, 150, 200, 250, 300):
        p_ = fit['projections'][f"{fit['better_model']}_n{tn}"]
        delta = p_['point'] - 0.5227
        delta_low = p_['ci_low'] - 0.5227
        delta_high = p_['ci_high'] - 0.5227
        print(f"{tn:>6}  Δ = {delta:+.4f} [{delta_low:+.4f},{delta_high:+.4f}]")


if __name__ == "__main__":
    main()
