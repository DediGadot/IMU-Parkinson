#!/usr/bin/env bash
# Launch the 4 most promising (item, variant) LOOCV runs in parallel.
# bags=4 for speed (vs default 16); will need to verify gain holds at higher bag counts.

set -e
cd /home/fiod/medical

# Each job runs sequentially within itself but multiple in parallel via xargs
JOBS=(
  "9 bagged_cccv2_hyresidual"
  "11 bagged_cccv2_itemonly"
  "13 bagged_cccv2_v2plusitem"
  "14 bagged_cccv2_v2plusitem"
)

# Deploy once first
rsync -az --exclude='__pycache__' --exclude='.git' --exclude='.claude' --exclude='*.pyc' \
  --exclude='*.log' --exclude='*.json' --exclude='data/' --exclude='results/' \
  --exclude='.venv' --exclude='catboost_info' --exclude='*.md' \
  -e "ssh -p 26843" . root@142.171.48.138:/root/pd-imu/ 2>/dev/null || true

# Run all 4 in parallel via SSH (each a separate sub-process on remote)
for spec in "${JOBS[@]}"; do
  read -r item variant <<<"$spec"
  ssh -p 26843 root@142.171.48.138 "cd /root/pd-imu && nohup python3 -u run_per_item_ccc_v3.py --items $item --variants $variant --eval loocv --tag cccv3bag4 --no-null --workers 1 --bags 4 > /root/pd-imu/loocv_${item}_${variant}.log 2>&1 &" &
done
wait
echo "All 4 LOOCV jobs launched on remote"
