"""T1 iter34 Phase 0 ablation orchestrator — run all 9 variants sequentially.

Variants (matches goal-v1 cells b + d):
  (b) drop-one chain: drop{9,10,11,12,13,14,15,18}  → 8 variants
  (d) no_k500                                       → 1 variant

For each variant: write_prereg → lockbox → next.

Total compute estimate (RTX 4060, 5 spawn workers): 9 × ~27 min ≈ 4 hours.

Resumable: skips variants whose lockbox JSON already exists (by glob).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from project_paths import RESULTS_DIR

VARIANTS = [
    "drop9", "drop10", "drop11", "drop12", "drop13", "drop14",
    "drop15", "drop18", "no_k500",
]

PY = sys.executable
SCRIPT = REPO_ROOT / "run_t1_iter34_phase0_ablation.py"


def _existing_lockbox(variant: str) -> Path | None:
    pat = f"lockbox_t1_iter34_phase0_{variant}_*.json"
    matches = sorted(RESULTS_DIR.glob(pat))
    return matches[-1] if matches else None


def _latest_prereg(variant: str) -> Path:
    pat = f"preregistration_t1_iter34_phase0_{variant}_*.json"
    matches = sorted(RESULTS_DIR.glob(pat))
    if not matches:
        raise FileNotFoundError(f"no prereg for variant {variant!r}")
    return matches[-1]


def run_variant(variant: str) -> None:
    if _existing_lockbox(variant):
        print(
            f"[SKIP] {variant}: lockbox already exists "
            f"({_existing_lockbox(variant).name})",
            flush=True,
        )
        return

    print(f"\n{'=' * 72}", flush=True)
    print(f"[PHASE 0] variant={variant}", flush=True)
    print(f"{'=' * 72}\n", flush=True)

    # Write prereg
    print(f"[{variant}] writing prereg...", flush=True)
    subprocess.run(
        [PY, str(SCRIPT), "--mode", "write_prereg", "--variant", variant],
        check=True, env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    prereg = _latest_prereg(variant)
    print(f"[{variant}] prereg = {prereg.name}", flush=True)

    # Lockbox
    print(f"[{variant}] running LOOCV lockbox...", flush=True)
    t0 = time.time()
    subprocess.run(
        [
            PY, str(SCRIPT), "--mode", "lockbox",
            "--variant", variant,
            "--preregistration_file", str(prereg),
        ],
        check=True, env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    wall = time.time() - t0
    print(f"[{variant}] done in {wall:.0f}s ({wall/60:.1f} min)", flush=True)


def main() -> None:
    print(f"Phase 0 orchestrator: {len(VARIANTS)} variants to run", flush=True)
    print(f"  variants = {VARIANTS}", flush=True)
    print(f"  results dir = {RESULTS_DIR}", flush=True)
    overall_t0 = time.time()
    for v in VARIANTS:
        run_variant(v)
    print(
        f"\n[PHASE 0 COMPLETE] all {len(VARIANTS)} variants done in "
        f"{time.time()-overall_t0:.0f}s",
        flush=True,
    )


if __name__ == "__main__":
    main()
