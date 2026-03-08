#!/usr/bin/env bash
# gpu.sh — master/slave GPU deployment.
#
# This machine is MASTER (source of truth). Remote is a disposable GPU slave.
# To swap GPU servers: change REMOTE + PORT below, run ./gpu.sh --setup, done.
#
# Usage:
#   ./gpu.sh <script.py> [args]   deploy code + run on GPU
#   ./gpu.sh --pull                fetch results (logs, json, csv) back
#   ./gpu.sh --status              check GPU utilization + running jobs
#   ./gpu.sh --log                 tail latest log on remote
#   ./gpu.sh --ssh                 open shell on remote
#   ./gpu.sh --setup               provision a fresh GPU server
#   ./gpu.sh --nuke                kill all python jobs on remote

set -euo pipefail

# === SLAVE CONFIG (change these two lines to swap servers) ===
REMOTE="${GPU_REMOTE:-root@46.228.83.78}"
PORT="${GPU_PORT:-40005}"
# =============================================================

REMOTE_DIR="/root/pd-imu"
SSH="ssh -p $PORT $REMOTE"

deploy() {
    rsync -az --delete \
        --exclude='__pycache__' \
        --exclude='.git' \
        --exclude='.claude' \
        --exclude='*.pyc' \
        --exclude='*.log' \
        --exclude='*.json' \
        --exclude='data/' \
        --exclude='results/' \
        --exclude='.venv' \
        --exclude='catboost_info' \
        --exclude='*.md' \
        -e "ssh -p $PORT" \
        . "$REMOTE:$REMOTE_DIR/"
    echo "deployed to $REMOTE:$REMOTE_DIR"
}

case "${1:-}" in
    --setup)
        echo "=== Provisioning GPU slave: $REMOTE ==="
        $SSH "mkdir -p $REMOTE_DIR"
        $SSH "pip install --quiet torch torchvision torchaudio \
            --index-url https://download.pytorch.org/whl/nightly/cu128 && \
            pip install --quiet numpy pandas scipy scikit-learn \
            xgboost catboost einops torchdiffeq"
        deploy
        echo ""
        echo "Done. Now sync data from an existing slave:"
        echo "  rsync -az -e 'ssh -p OLD_PORT' OLD_REMOTE:$REMOTE_DIR/data/ \\"
        echo "    \$($SSH echo $REMOTE_DIR/data/)"
        echo ""
        echo "Or download fresh:"
        echo "  ./gpu.sh synapse_download.py"
        ;;
    --pull)
        echo "pulling results from $REMOTE..."
        rsync -az \
            --include='*.log' --include='*.json' --include='*.csv' \
            --include='results/' --include='results/**' \
            --exclude='*' \
            -e "ssh -p $PORT" \
            "$REMOTE:$REMOTE_DIR/" ./results/
        echo "done → ./results/"
        ;;
    --status)
        $SSH "nvidia-smi; echo; ps aux | grep -E 'python.*run_' | grep -v grep || echo 'no jobs running'"
        ;;
    --log)
        $SSH "ls -t $REMOTE_DIR/*.log 2>/dev/null | head -1 | xargs tail -f"
        ;;
    --ssh)
        exec $SSH "cd $REMOTE_DIR && exec bash"
        ;;
    --nuke)
        $SSH "pkill -f 'python.*run_' && echo 'killed all python jobs' || echo 'nothing to kill'"
        ;;
    "")
        echo "usage: ./gpu.sh <script.py> [args]   deploy + run"
        echo "       ./gpu.sh --pull                fetch results"
        echo "       ./gpu.sh --status              GPU + jobs"
        echo "       ./gpu.sh --log                 tail latest log"
        echo "       ./gpu.sh --ssh                 shell into slave"
        echo "       ./gpu.sh --setup               provision new slave"
        echo "       ./gpu.sh --nuke                kill all jobs"
        exit 1
        ;;
    *)
        deploy
        SCRIPT="$1"; shift
        echo "running: python3 -u $SCRIPT $*"
        $SSH "cd $REMOTE_DIR && python3 -u $SCRIPT $*"
        ;;
esac
