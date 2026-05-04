#!/bin/bash
# Launch Phases 4+5+6 maximizing CPU+GPU utilization on 17-core RTX 5070 server.
cd /root/pd-imu
mkdir -p /tmp/p456_logs

# Phase 5 (GPU): one process iterates 12 configs sequentially.
nohup python3 -u run_phase5_fm_adapter.py --variant all --target all \
  > /tmp/p456_logs/phase5_gpu.log 2>&1 &
echo "Phase 5 (GPU) launched: pid $!"

# Phase 4 + Phase 6: 21 + 12 = 33 CPU jobs at xargs -P 8 (8 in flight at any time).
JOBS_FILE=/tmp/p456_logs/jobs.txt
> "$JOBS_FILE"
for v in teacher_only student_v2_no_kd student_vfm_no_kd student_v2_kd_a05 student_v2_kd_a02 student_vfm_kd_a05 student_vfm_kd_a02; do
  for t in t1 t2 t3; do
    echo "phase4_distill $v $t" >> "$JOBS_FILE"
  done
done
for v in stack_avg stack_concat stack_lgb_meta stack_lr_meta; do
  for t in t1 t2 t3; do
    echo "phase6_stack $v $t" >> "$JOBS_FILE"
  done
done

run_one() {
  local phase=$1
  local v=$2
  local t=$3
  local log=/tmp/p456_logs/${phase}_${v}_${t}.log
  PD_IMU_N_CORES=2 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 \
    python3 -u "/root/pd-imu/run_${phase}.py" --variant "$v" --target "$t" > "$log" 2>&1
  echo "Finished $phase $v $t"
}
export -f run_one

nohup bash -c '
  cat '"$JOBS_FILE"' | xargs -P 8 -L 1 bash -c "run_one \$0 \$1 \$2"
' > /tmp/p456_logs/_xargs.log 2>&1 &
echo "CPU batch (33 jobs at -P 8) launched: pid $!"

echo "Total: 33 CPU jobs + 1 GPU process"
