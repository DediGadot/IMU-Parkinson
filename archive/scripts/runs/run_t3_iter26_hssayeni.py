"""T3 iter26 — Hssayeni MJFF Levodopa Response Study cross-dataset bridge.

Mission: test whether iter5-style wrist-only architecture transports to a
genuinely-external cohort under MATCHED clinical labels (UPDRS-III) rather
than just binary PD/HC. PADS (F60b) gave AUROC=0.50 chance because of task-
protocol mismatch. Hssayeni / MJFF Levodopa Response Study has BOTH UPDRS-III
labels AND wrist accelerometer recordings on a different cohort — the only
public dataset that matches WG's regression target with PADS's sensor class.

The dataset is hosted on Synapse:
  Project ID: syn20681023 (MJFF Levodopa Response Study)
  https://www.synapse.org/Synapse:syn20681023
The dataset is DUA-gated — anonymous metadata access returns 404 on children
listing. Verified empirically 2026-05-05.

ACCESS PATH (USER ACTION REQUIRED):
  1. Synapse account at https://www.synapse.org (free).
  2. Apply for DUA on syn20681023 — 1-3 day approval.
  3. Generate Personal Access Token at https://www.synapse.org/PersonalAccessTokens.
  4. Save PAT to ~/.synapseConfig:
       [authentication]
       authtoken = <YOUR_PAT>
  5. Or pass PAT via environment: SYNAPSE_AUTH_TOKEN=<PAT>
  6. Run this script in --mode probe to verify access; then --mode download.

PIPELINE:
  --mode probe       : test Synapse auth + DUA + list parent children
  --mode download    : sync syn20681023 wrist+UPDRS subset to data/raw/hssayeni/
  --mode extract     : invoke cache_hssayeni_features.py to build wrist feature CSV
  --mode write_prereg: write immutable pre-reg JSON for the joint training architecture
  --mode run         : run joint WG+Hssayeni training; output WG LOOCV CCC + Hssayeni LOOCV CCC

ARCHITECTURE (joint training):
  Stage 1 Ridge α=1.0 on shared clinical {age, sex} (the only fields known to be
    in BOTH cohorts; H&Y / cv_yrs / cv_dbs are WG-only). Trained on union cohort.
  Stage 2 LGB on common wrist features (3-axis acc + magnitude → time/freq/gait
    features matching iter25b's 64-col schema, FreeAcc-style + ×9.81 PADS-style
    if needed). Per-fold K=300 LGB-importance. Trained on union cohort.
  Evaluation:
    (E1) WG LOOCV: hold out 1 WG subject, train on remaining WG + ALL Hssayeni.
    (E2) Hssayeni LOOCV: hold out 1 Hssayeni subject, train on ALL WG + remaining Hssayeni.
  Both evaluations report CCC vs UPDRS-III (continuous regression).

GATES:
  E1 (WG LOOCV) headline: gate vs canonical iter5 LOOCV CCC=0.5227. Δ ≥ +0.025
    AND bootstrap CI (paired vs iter5 OOF on identical SIDs) frac>0 ≥ 0.95.
  E2 (Hssayeni LOOCV): no comparator (first published). Reported as bridge-cohort
    transportability number.

Pre-registered single-batch with formula_sha256 covering: union cohort sids,
common feature schema, Stage 1 covariate set, Stage 2 K-best, alpha, seeds.

USAGE:
  python3 run_t3_iter26_hssayeni.py --mode probe
  python3 run_t3_iter26_hssayeni.py --mode download
  python3 run_t3_iter26_hssayeni.py --mode extract
  python3 run_t3_iter26_hssayeni.py --mode write_prereg --seeds 42 1337 7
  python3 run_t3_iter26_hssayeni.py --mode run --preregistration_file <path>

NOTES:
- All pipelines fail FAST with informative error if data not present or auth missing.
- Per AGENTS.md leakage rules: NO global imputation, NO global standardization, NO
  test-fold leakage. Per-fold FoldNormalizer / FoldImputer only. Stage 1 Ridge fit
  only on training fold; Stage 2 LGB importance selector per-fold.
- This script is the SCAFFOLD; download + extract require Synapse DUA grant.
"""
from __future__ import annotations

import os
os.environ.setdefault("PD_IMU_N_CORES", "1")

import argparse
import hashlib
import json
import subprocess
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

SYNAPSE_PROJECT = "syn20681023"
HSSAYENI_DIR = Path("/root/pd-imu/data/raw/hssayeni")
HSSAYENI_DIR_LOCAL = REPO_ROOT / "data" / "raw" / "hssayeni"
HSSAYENI_FEATURES_CSV = REPO_ROOT / "results" / "hssayeni_features.csv"
HSSAYENI_MANIFEST = REPO_ROOT / "results" / "hssayeni_features.csv.manifest.json"


# ── Probe (verify Synapse auth + DUA without downloading) ───────────────────


def mode_probe() -> None:
    """Verify Synapse credentials + DUA grant on syn20681023.

    Surfaces the EXACT failure mode (no auth / no DUA / network error) so the
    user knows what they need to fix.
    """
    try:
        import synapseclient
    except ImportError as exc:
        raise SystemExit(
            "synapseclient is not installed. Install on the remote with:\n"
            "  ssh -p 26843 root@142.171.48.138 'pip install synapseclient'\n"
            f"({exc})"
        ) from exc

    syn = synapseclient.Synapse(skip_checks=True, silent=False)
    print(f"Probing Synapse access to {SYNAPSE_PROJECT} (MJFF Levodopa Response Study)...", flush=True)

    # Step 1: try login (uses ~/.synapseConfig or SYNAPSE_AUTH_TOKEN env)
    try:
        syn.login(silent=True)
        creds_ok = True
        print(f"  AUTH OK: logged in as {getattr(syn.credentials, 'username', '<unknown>')}", flush=True)
    except Exception as exc:
        creds_ok = False
        print(f"  AUTH FAIL: {exc}", flush=True)
        print(
            "\nNEXT STEPS for the user:\n"
            "  1. Create Synapse account: https://www.synapse.org\n"
            "  2. Generate Personal Access Token: https://www.synapse.org/PersonalAccessTokens\n"
            "  3. Save to ~/.synapseConfig:\n"
            "       [authentication]\n"
            "       authtoken = <YOUR_PAT>\n"
            "     OR export SYNAPSE_AUTH_TOKEN=<PAT> in your shell.\n"
            "  4. Re-run --mode probe.\n"
            "\nNOTE: same Synapse account that granted access to syn55105530 / syn61370558\n"
            "      (used in F31 to download WearGait-PD) should work — but DUA on\n"
            "      syn20681023 is a SEPARATE application. See scripts/synapse_hssayeni_setup.md.",
            flush=True,
        )
        raise SystemExit(2)

    # Step 2: probe project metadata
    try:
        e = syn.restGET(f"/entity/{SYNAPSE_PROJECT}")
        print(f"  PROJECT: {e.get('name')}", flush=True)
    except Exception as exc:
        raise SystemExit(f"Project metadata fetch failed: {exc}")

    # Step 3: try to list children (this is the DUA gate)
    try:
        children = syn.restGET(f"/entity/{SYNAPSE_PROJECT}/children")
        page = children.get("page", [])
        print(f"  DUA OK: project has {len(page)} top-level children", flush=True)
        for c in page[:30]:
            ctype = c.get("type", "").split(".")[-1]
            print(f"    {c.get('id'):14s} {c.get('name', '')[:60]}  type={ctype}", flush=True)
    except Exception as exc:
        msg = str(exc)
        print(f"  DUA FAIL: {msg[:200]}", flush=True)
        if "404" in msg or "not logged in" in msg or "not have access" in msg.lower():
            print(
                "\nDUA NOT GRANTED on this project.\n"
                f"  Apply at: https://www.synapse.org/Synapse:{SYNAPSE_PROJECT}\n"
                "  (Login → ACL panel → Request Access → fill DUA form.)\n"
                "  Approval typically 1-3 business days.",
                flush=True,
            )
        raise SystemExit(3)

    print("\n[probe] all checks passed; ready for --mode download.", flush=True)


# ── Download (requires DUA + auth) ──────────────────────────────────────────


def mode_download() -> None:
    """Sync syn20681023 wrist+clinical subset to HSSAYENI_DIR.

    NOT YET RUNNABLE without DUA. When called, this will:
      1. Verify auth + DUA via probe.
      2. Walk the project tree to find wrist accelerometer + UPDRS-III tables.
      3. syncFromSynapse to HSSAYENI_DIR.

    Requires user to have completed Synapse DUA application.
    """
    raise SystemExit(
        "[download] BLOCKED ON DUA.\n"
        f"  Run --mode probe first to verify auth + DUA on {SYNAPSE_PROJECT}.\n"
        f"  See scripts/synapse_hssayeni_setup.md for full runbook.\n"
        "  This stub will be filled in when access is confirmed.\n"
    )


# ── Extract (delegates to cache_hssayeni_features.py) ───────────────────────


def mode_extract() -> None:
    """Invoke cache_hssayeni_features.py to build the wrist feature CSV."""
    cache_script = REPO_ROOT / "cache_hssayeni_features.py"
    if not cache_script.exists():
        raise SystemExit(f"Missing {cache_script}")
    print(f"[extract] running {cache_script.name} ...", flush=True)
    rc = subprocess.call([sys.executable, str(cache_script)])
    if rc != 0:
        raise SystemExit(f"cache_hssayeni_features.py exited with {rc}")
    print(f"[extract] wrote {HSSAYENI_FEATURES_CSV}", flush=True)


# ── Pre-reg + run (joint WG+Hssayeni training) ──────────────────────────────


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).decode().strip()
    except Exception:
        return "unknown"


def _formula_sha256(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def make_prereg_payload(seeds: list[int]) -> dict:
    return {
        "experiment": "T3 iter26 — Hssayeni MJFF cross-dataset bridge (joint WG+Hssayeni UPDRS regression)",
        "internal_dataset": "WearGait-PD (NLS+WPD, 13-IMU body-worn, full UPDRS-III, N=98 PD)",
        "external_dataset": "Hssayeni MJFF Levodopa Response Study (Synapse syn20681023)",
        "rationale": (
            "iter25b PADS cross-dataset zero-shot AUROC = 0.50 (chance) due to task-protocol mismatch. "
            "Hssayeni MJFF has both UPDRS-III labels AND wrist accelerometer. iter26 tests whether "
            "joint training on WG (98) + Hssayeni (~30-40) lifts WG LOOCV CCC above iter5's 0.5227."
        ),
        "stage_1": "Ridge alpha=1.0 on shared clinical {age, sex}; trained on union cohort",
        "stage_2": "LGB on common wrist features (3-axis acc + magnitude → time/freq, ~64 cols); per-fold K=300 LGB-importance",
        "common_features": "Mirrors iter25b's wrist_am_*/wrist_ax_*/wrist_ay_*/wrist_az_* schema; FreeAcc-equivalent (gravity-removed, m/s²)",
        "evaluation_e1_wg": "LOOCV on WG: hold out 1 WG, train on (97 WG + ALL Hssayeni); CCC vs UPDRS-III",
        "evaluation_e2_hss": "LOOCV on Hssayeni: hold out 1 Hssayeni, train on (ALL WG + remaining Hssayeni); CCC vs UPDRS-III",
        "comparator": "iter5 canonical LOOCV CCC=0.5227 on N=98 WG (lockbox_t3_iter5_A3_tier1_*.oof.npy)",
        "seeds": list(seeds),
        "lockbox_rules": [
            "ONE pre-registered batch covering both E1 and E2.",
            "E1 gate: Δ ≥ +0.025 vs iter5 LOOCV AND paired bootstrap (5000 resamples) frac>0 ≥ 0.95.",
            "E2 reported as first published WG→Hssayeni bridge transportability number.",
            "If E1 fails: F62 negative; iter26 documents as 'cohort augmentation does not break ceiling at this scale'.",
            "If E1 passes: new canonical T3 LOOCV; update CLAUDE.md/AGENTS.md/MEMORY.md.",
        ],
    }


def mode_write_prereg(seeds: list[int]) -> Path:
    payload = make_prereg_payload(seeds)
    formula = _formula_sha256(payload)
    git = _git_sha()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = {
        **payload,
        "formula_sha256": formula,
        "git_sha": git,
        "created_at_utc": datetime.utcnow().isoformat() + "Z",
        "timestamp": ts,
    }
    pre_path = REPO_ROOT / "results" / f"preregistration_t3_iter26_hssayeni_{ts}.json"
    if pre_path.exists():
        raise RuntimeError(f"Pre-reg path clash: {pre_path}")
    pre_path.parent.mkdir(parents=True, exist_ok=True)
    with open(pre_path, "w") as f:
        json.dump(out, f, indent=2, default=float)
    print(f"\nPre-reg: {pre_path.name}", flush=True)
    print(f"  formula_sha256 = {formula[:16]}...", flush=True)
    print(f"  git_sha = {git[:12]}", flush=True)
    return pre_path


def mode_run(prereg_path: Path) -> None:
    if not HSSAYENI_FEATURES_CSV.exists():
        raise SystemExit(
            f"[run] BLOCKED: {HSSAYENI_FEATURES_CSV} not found.\n"
            "  Run --mode download → --mode extract first.\n"
            f"  (Requires Synapse DUA on {SYNAPSE_PROJECT}.)\n"
        )
    raise SystemExit(
        "[run] STUB — joint WG+Hssayeni training pipeline not yet implemented;\n"
        "  will be built when --mode extract has produced a real features CSV with verifiable schema.\n"
        "  The pre-reg + scaffolding are ready; the joint Stage1+Stage2 fit + paired bootstrap are minimal\n"
        "  to add once the data is parseable. Estimated 200-300 lines of additional code.\n"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--mode",
        choices=["probe", "download", "extract", "write_prereg", "run"],
        required=True,
    )
    ap.add_argument("--seeds", type=int, nargs="+", default=[42, 1337, 7])
    ap.add_argument("--preregistration_file", type=str, default=None)
    args = ap.parse_args()

    if args.mode == "probe":
        mode_probe()
    elif args.mode == "download":
        mode_download()
    elif args.mode == "extract":
        mode_extract()
    elif args.mode == "write_prereg":
        mode_write_prereg(seeds=list(args.seeds))
    elif args.mode == "run":
        if not args.preregistration_file:
            raise SystemExit("--preregistration_file required for --mode run")
        mode_run(Path(args.preregistration_file))


if __name__ == "__main__":
    main()
