#!/usr/bin/env bash
# Parallel driver for /tmp/pro-results.txt ablation: S1, S2, S3, S5, S6, S7
# Designed to run on remote slave (fiod@165.22.71.91:2243).
# Pre-registration: results/preregistration_t1t3_proresults_ablation_20260515T133800Z.json
set -u

cd "$(dirname "$0")"
mkdir -p logs

# Slave venv python (matches gpu.sh PY)
PY="${PY:-/home/fiod/pd-imu/.venv/bin/python3}"
if [ ! -x "$PY" ]; then
    # Fallback for local execution
    PY="$(which python3)"
    echo "[WARN] slave venv python not found, using $PY"
fi

# Concurrency bound: up to 4 jobs in flight (each is ~1-2 cores, 17-core slave; OMP_NUM_THREADS=2)
MAX_JOBS=4
export OMP_NUM_THREADS=2
export OPENBLAS_NUM_THREADS=2
export MKL_NUM_THREADS=2

launch() {
    local slot="$1"
    local cmd="$2"
    local log="logs/$(date -u +%Y%m%dT%H%M%SZ)_${slot}.log"
    echo "[$(date -u +%FT%TZ)] LAUNCH $slot → $log"
    bash -c "$cmd" > "$log" 2>&1 &
    sleep 0.5
    # Throttle to MAX_JOBS in flight
    while [ "$(jobs -r -p | wc -l)" -ge "$MAX_JOBS" ]; do
        sleep 2
    done
}

# Phase 1: Real-mode runs (6 slots)
launch S1 "$PY -u run_t1_S1_sumaware_bayesian.py"
launch S2 "$PY -u run_t1_S2_topofractal8.py"
launch S3 "$PY -u run_t1_S3_ordinal_composer.py"
launch S5 "$PY -u run_t1_S5_microbatch_item13only_audit.py"
launch S6 "$PY -u run_t1_S6_stability_sparse_score.py"
launch S7 "$PY -u run_t1_S7_multiitem_topology_abstention.py"

wait
echo "[$(date -u +%FT%TZ)] REAL-MODE COMPLETE"

# Phase 2: 5-null gate (scrambled-y + sid-shuffle) for the four headline T1 CCC slots
launch S1_n1 "$PY -u run_t1_S1_sumaware_bayesian.py --null=scrambled_y"
launch S2_n1 "$PY -u run_t1_S2_topofractal8.py --null=scrambled_y"
launch S3_n1 "$PY -u run_t1_S3_ordinal_composer.py --null=scrambled_y"
launch S5_n1 "$PY -u run_t1_S5_microbatch_item13only_audit.py --null=scrambled_y"
launch S7_n1 "$PY -u run_t1_S7_multiitem_topology_abstention.py --null=scrambled_y"

launch S1_n2 "$PY -u run_t1_S1_sumaware_bayesian.py --null=sid_shuffle"
launch S2_n2 "$PY -u run_t1_S2_topofractal8.py --null=sid_shuffle"
launch S3_n2 "$PY -u run_t1_S3_ordinal_composer.py --null=sid_shuffle"
launch S5_n2 "$PY -u run_t1_S5_microbatch_item13only_audit.py --null=sid_shuffle"
launch S7_n2 "$PY -u run_t1_S7_multiitem_topology_abstention.py --null=sid_shuffle"

wait
echo "[$(date -u +%FT%TZ)] NULL-MODE COMPLETE"

# Phase 3: S7 sanity-y-nan receipt
"$PY" -u run_t1_S7_multiitem_topology_abstention.py --sanity-y-nan
echo "[$(date -u +%FT%TZ)] SANITY-Y-NAN COMPLETE"

echo "[$(date -u +%FT%TZ)] ALL JOBS DONE"
echo "--- lockbox JSONs ---"
ls -lat results/lockbox_t1_S*_*.json 2>/dev/null | head -30
echo "--- abstention sanity ---"
ls -lat results/abstention_sanity_*.json 2>/dev/null | head -5
echo "--- OOF NPZ ---"
ls -lat results/oof_t1_S*_*.npz 2>/dev/null | head -10
