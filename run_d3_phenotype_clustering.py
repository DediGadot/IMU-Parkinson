"""D3: Unsupervised PH+MFDFA phenotype clustering and residual stratification.

Hypothesis: PH + MFDFA features encode 2-3 latent biomechanical phenotypes
(e.g., axial-dominant vs limb-dominant, or tremor-dominant vs PIGD). If
phenotype identity stratifies iter34 residuals, a mixture-of-experts /
phenotype-gated correction is a next-iteration design.

Descriptive only - not a CCC push. No FWER cost.

Method:
  1. Project PH + MFDFA features to PCA k=5 (fold-local? no - this is descriptive
     so global PCA is acceptable as long as we document it).
  2. KMeans k in {2, 3, 4}; pick best silhouette.
  3. For each cluster: compute residual variance (iter34 OOF), AND mean truth,
     AND test whether residual mean differs significantly across clusters.
  4. If clusters stratify residuals (e.g., one cluster has 2x worse residual
     variance), report as descriptive finding for the paper + next-iter design.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer

from eval_utils import lins_ccc as ccc

CACHE_PATH = "results/cache_stepfunction_spd_klc_crqa_mfdfa_ph_20260515T072624Z.csv"
OOF_PATH = "results/t1_iter34_per_item_oof_20260511_044242.npz"


def main():
    df = pd.read_csv(CACHE_PATH)
    oof = dict(np.load(OOF_PATH, allow_pickle=True))
    sids_oof = oof["sids"].astype(str)
    keep = df["sid"].isin(sids_oof).values
    df = df[keep].reset_index(drop=True)
    sid_to_row = {s: i for i, s in enumerate(df["sid"].astype(str).values)}
    order = np.array([sid_to_row[s] for s in sids_oof])
    df = df.iloc[order].reset_index(drop=True)
    n = len(df)
    print(f"[D3] N={n} subjects aligned")

    # Feature set: all PH + all MFDFA cols across all tasks
    feat_cols = [c for c in df.columns if "_ph_" in c or "_mfdfa_" in c]
    print(f"[D3] Feature columns: {len(feat_cols)}")
    X = df[feat_cols].values.astype(float)

    # Impute + scale + PCA (global - descriptive analysis, not for CCC reporting)
    X_imp = SimpleImputer(strategy="median").fit_transform(X)
    X_sc = StandardScaler().fit_transform(X_imp)
    pca = PCA(n_components=min(10, X_sc.shape[1]))
    X_pca = pca.fit_transform(X_sc)
    var_ratio = pca.explained_variance_ratio_
    print(f"[D3] PCA top-5 explained variance: "
          f"{var_ratio[:5].sum()*100:.1f}% (per-component: {var_ratio[:5].round(3).tolist()})")

    # Cluster sweep
    sil_scores = {}
    cluster_results = {}
    for k in [2, 3, 4]:
        km = KMeans(n_clusters=k, random_state=42, n_init=20)
        labels = km.fit_predict(X_pca[:, :5])
        sil = silhouette_score(X_pca[:, :5], labels)
        sil_scores[k] = float(sil)
        cluster_results[k] = labels.tolist()
        print(f"[D3] k={k} silhouette={sil:.4f}, cluster sizes={np.bincount(labels).tolist()}")

    best_k = max(sil_scores, key=lambda k: sil_scores[k])
    labels = np.array(cluster_results[best_k])
    print(f"[D3] Best k={best_k} (silhouette {sil_scores[best_k]:.4f})")

    # Residual stratification by cluster (iter34 T1 sum residual)
    y_true = oof["y_t1"].astype(float)
    y_pred = oof["t1_sum_pred"].astype(float)
    resid = y_true - y_pred
    abs_resid = np.abs(resid)

    cluster_stats = {}
    for c in range(best_k):
        m = labels == c
        cluster_stats[f"cluster_{c}"] = {
            "n_subjects": int(m.sum()),
            "mean_y_t1": round(float(y_true[m].mean()), 3),
            "std_y_t1": round(float(y_true[m].std()), 3),
            "mean_iter34_pred": round(float(y_pred[m].mean()), 3),
            "mean_resid": round(float(resid[m].mean()), 3),
            "mean_abs_resid": round(float(abs_resid[m].mean()), 3),
            "var_resid": round(float(resid[m].var()), 4),
            "ccc_within_cluster": round(float(ccc(y_true[m], y_pred[m]))
                                       if m.sum() >= 5 else np.nan, 4),
        }
        print(f"     cluster {c}: n={cluster_stats[f'cluster_{c}']['n_subjects']:2d}, "
              f"mean_y={cluster_stats[f'cluster_{c}']['mean_y_t1']:.2f}, "
              f"var_resid={cluster_stats[f'cluster_{c}']['var_resid']:.3f}, "
              f"CCC={cluster_stats[f'cluster_{c}']['ccc_within_cluster']:.4f}")

    # Test whether residual variance differs across clusters (Levene + ANOVA)
    cluster_resids = [resid[labels == c] for c in range(best_k)]
    levene_stat, levene_p = stats.levene(*cluster_resids)
    f_stat, anova_p = stats.f_oneway(*cluster_resids)
    print(f"\n[D3] Cluster residual heterogeneity tests:")
    print(f"     Levene  (variance heterogeneity): F={levene_stat:.4f}, p={levene_p:.4f}")
    print(f"     ANOVA   (mean heterogeneity):     F={f_stat:.4f}, p={anova_p:.4f}")

    # Per-item stratification at best k
    items = [9, 10, 11, 12, 13, 14]
    per_item_strat = {}
    for it in items:
        yt = oof[f"item_{it}_true"].astype(float)
        yp = oof[f"item_{it}_pred"].astype(float)
        res = yt - yp
        cluster_res = [res[labels == c] for c in range(best_k)]
        lev_s, lev_p = stats.levene(*cluster_res)
        per_item_strat[f"item_{it}"] = {
            "levene_F": round(float(lev_s), 4),
            "levene_p": round(float(lev_p), 4),
            "var_per_cluster": [round(float(np.var(cr)), 4) for cr in cluster_res],
        }

    # Verdict
    if levene_p < 0.05:
        verdict = "PHENOTYPE_STRATIFIES_RESIDUAL"
        rationale = (f"Cluster identity (k={best_k}) significantly stratifies iter34 T1 sum residual "
                     f"variance (Levene p={levene_p:.4f}). A mixture-of-experts / phenotype-gated "
                     f"correction is a plausible next-iteration design.")
    elif sil_scores[best_k] < 0.10:
        verdict = "NO_CLEAR_PHENOTYPE_STRUCTURE"
        rationale = (f"Best silhouette {sil_scores[best_k]:.4f} - clusters are weak/spurious. "
                     f"PH+MFDFA features do not encode discrete latent phenotypes at N={n}.")
    else:
        verdict = "PHENOTYPE_PRESENT_BUT_NO_RESIDUAL_STRATIFICATION"
        rationale = (f"Clusters are present (silhouette {sil_scores[best_k]:.4f}) but do NOT "
                     f"stratify iter34 residuals (Levene p={levene_p:.4f}). Phenotypes are "
                     f"orthogonal to iter34's error mode - mixture-of-experts unlikely to help.")

    print(f"\n[D3] VERDICT: {verdict}")
    print(f"     {rationale}")

    out = {
        "name": "d3_phenotype_clustering",
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "n_subjects": n,
        "n_features": len(feat_cols),
        "pca_top5_explained_var": round(float(var_ratio[:5].sum()), 4),
        "silhouette_per_k": {str(k): round(v, 4) for k, v in sil_scores.items()},
        "best_k": best_k,
        "cluster_sizes": np.bincount(labels).tolist(),
        "cluster_stats_t1_sum_residual": cluster_stats,
        "per_item_residual_heterogeneity": per_item_strat,
        "levene_test_t1_sum_resid": {
            "F": round(float(levene_stat), 4),
            "p": round(float(levene_p), 4),
        },
        "anova_test_t1_sum_resid": {
            "F": round(float(f_stat), 4),
            "p": round(float(anova_p), 4),
        },
        "verdict": verdict,
        "rationale": rationale,
        "caveat": (
            "Clustering performed on subject-level features with GLOBAL PCA + KMeans (not "
            "fold-local). Acceptable for descriptive phenotype discovery; would need "
            "fold-local refit before any CCC-pushing downstream use to avoid leakage."
        ),
    }
    ts = out["created_at_utc"]
    path = Path(f"results/d3_phenotype_clustering_{ts}.json")
    path.write_text(json.dumps(out, indent=2))
    print(f"\n[D3] Wrote {path}")


if __name__ == "__main__":
    main()
