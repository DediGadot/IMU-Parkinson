"""
Protocol-matched DL rebenchmark on the fresh split.

Runs only the strongest historical DL candidates under the corrected
five-task test protocol so the comparison against the feature stack is
apples-to-apples.
"""
from __future__ import annotations

import time

from project_paths import REPO_ROOT, save_json_artifact

import sys

sys.path.insert(0, str(REPO_ROOT))

from run_dl_experiments import (  # noqa: E402
    ALL_TASKS,
    DEVICE,
    InceptionTimeEncoder,
    MILModel,
    N_CH,
    PatchEncoder,
    load_all_data,
    load_covariates,
    load_split,
    parse_clinical,
    run_experiment,
)


def main():
    t0 = time.time()
    print("=" * 80)
    print("DL REBENCHMARK — FRESH SPLIT, FIVE-TASK TEST")
    print(f"Device: {DEVICE}")
    print("=" * 80)

    subjects = parse_clinical()
    split = load_split()
    dev_sids, test_sids = split["dev_sids"], split["test_sids"]
    covs = load_covariates()

    X_dev, y_dev, s_dev, X_test, y_test, s_test, X_all, g_mean, g_std = load_all_data(
        subjects, dev_sids, test_sids
    )
    print(f"Protocol: dev/test both use tasks={ALL_TASKS}")

    results = []
    results.append(
        run_experiment(
            "P3B: InceptionTime 3blk + ordinal (five-task test)",
            lambda: MILModel(InceptionTimeEncoder(N_CH, 32, 3), ordinal=True),
            X_dev,
            y_dev,
            s_dev,
            X_test,
            y_test,
            s_test,
            covs,
        )
    )
    results.append(
        run_experiment(
            "P1A: MAE->Transformer 128d/4L + MIL (five-task test)",
            lambda: MILModel(PatchEncoder(N_CH, 128, 4, 4)),
            X_dev,
            y_dev,
            s_dev,
            X_test,
            y_test,
            s_test,
            covs,
        )
    )

    payload = {
        "protocol": {
            "fresh_outer_holdout": True,
            "five_task_test": True,
            "tasks": list(ALL_TASKS),
            "models": [row["name"] for row in results],
        },
        "results": results,
        "runtime_min": round((time.time() - t0) / 60, 1),
    }
    save_json_artifact("dl_experiment_results.json", payload)
    save_json_artifact("dl_rebenchmark_results.json", payload)
    print("\nSaved DL rebenchmark artifacts to results/ and repo root mirror")


if __name__ == "__main__":
    main()
