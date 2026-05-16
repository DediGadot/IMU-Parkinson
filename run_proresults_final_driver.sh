#!/usr/bin/env bash
# Final probe driver: S8 (item-12 MFDFA + item-13 PH joint) + S9 (TUG-localized variant).
set -u
cd "$(dirname "$0")"
mkdir -p logs

PY="${PY:-/home/fiod/pd-imu/.venv/bin/python3}"
[ -x "$PY" ] || PY="$(which python3)"

export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2

STAMP=$(date -u +%Y%m%dT%H%M%SZ)

echo "[$(date -u +%FT%TZ)] LAUNCH S8 real"
"$PY" -u run_t1_S8_item12mfdfa_item13ph_joint.py > "logs/${STAMP}_S8.log" 2>&1 &
PID_S8=$!
echo "[$(date -u +%FT%TZ)] LAUNCH S9 real"
"$PY" -u run_t1_S9_tug_localized_ph_mfdfa.py > "logs/${STAMP}_S9.log" 2>&1 &
PID_S9=$!
wait $PID_S8 $PID_S9
echo "[$(date -u +%FT%TZ)] REAL DONE (S8=$? S9 also done)"

echo "[$(date -u +%FT%TZ)] LAUNCH null modes"
"$PY" -u run_t1_S8_item12mfdfa_item13ph_joint.py --null=scrambled_y > "logs/${STAMP}_S8_n1.log" 2>&1 &
"$PY" -u run_t1_S9_tug_localized_ph_mfdfa.py --null=scrambled_y > "logs/${STAMP}_S9_n1.log" 2>&1 &
"$PY" -u run_t1_S8_item12mfdfa_item13ph_joint.py --null=sid_shuffle > "logs/${STAMP}_S8_n2.log" 2>&1 &
"$PY" -u run_t1_S9_tug_localized_ph_mfdfa.py --null=sid_shuffle > "logs/${STAMP}_S9_n2.log" 2>&1 &
wait
echo "[$(date -u +%FT%TZ)] NULL DONE"

echo "[$(date -u +%FT%TZ)] ALL DONE"
echo "--- lockboxes ---"
ls -lat results/lockbox_t1_S{8,9}_*.json 2>/dev/null | head -10
