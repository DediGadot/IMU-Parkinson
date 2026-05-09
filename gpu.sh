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
REMOTE="${GPU_REMOTE:-fiod@165.22.71.91}"
PORT="${GPU_PORT:-2243}"
# =============================================================

REMOTE_DIR="/home/fiod/pd-imu"
VENV="$REMOTE_DIR/.venv"
PY="$VENV/bin/python3"
PIP="$VENV/bin/pip"
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
        $SSH "mkdir -p $REMOTE_DIR/results"

        # 0. Create venv (Ubuntu 24.04+ enforces PEP 668 externally-managed env)
        echo "--- Creating Python venv at $VENV ---"
        $SSH "command -v python3 >/dev/null && python3 -m venv --help >/dev/null 2>&1 || (echo 'installing python3-venv'; sudo apt-get update -qq && sudo apt-get install -y python3-venv python3-full)"
        $SSH "[ -d $VENV ] || python3 -m venv $VENV"
        $SSH "$PIP install --quiet --upgrade pip wheel setuptools"

        # 1. Install PyTorch with CUDA support
        echo "--- Installing PyTorch (CUDA 12.8) ---"
        $SSH "$PIP install --quiet torch torchvision torchaudio \
            --index-url https://download.pytorch.org/whl/nightly/cu128"

        # 2. Deploy code + requirements file
        deploy

        # 3. Install all other dependencies from pinned requirements
        echo "--- Installing dependencies from requirements-gpu.txt ---"
        $SSH "cd $REMOTE_DIR && $PIP install --quiet -r requirements-gpu.txt"

        # 4. Verify critical imports
        echo "--- Verifying installation ---"
        $SSH "$PY -c '
import torch, lightgbm, xgboost, catboost, momentfm, shap, aeon
print(f\"torch {torch.__version__}, CUDA: {torch.cuda.is_available()}\")
print(f\"lightgbm {lightgbm.__version__}, xgboost {xgboost.__version__}\")
print(f\"momentfm {momentfm.__version__}\")
print(\"All imports OK\")
'"

        echo ""
        echo "=== Setup complete. Next steps: ==="
        echo ""
        echo "  # Upload cached artifacts (saves hours of recomputation):"
        echo "  rsync -az -e 'ssh -p $PORT' results/*.npz results/ablation_v3_features.csv \\"
        echo "      $REMOTE:$REMOTE_DIR/results/"
        echo ""
        echo "  # Upload dataset from another slave:"
        echo "  rsync -az -e 'ssh -p OLD_PORT' OLD_REMOTE:$REMOTE_DIR/data/ \\"
        echo "      \$($SSH echo $REMOTE_DIR/data/)"
        echo ""
        echo "  # Or download fresh (requires Synapse credentials):"
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
    --push-cache)
        echo "=== Uploading cached artifacts to $REMOTE ==="
        $SSH "mkdir -p $REMOTE_DIR/results $REMOTE_DIR/results/sensor_fm_cache"
        rsync -avz --progress \
            -e "ssh -p $PORT" \
            results/fm_embeddings.npz \
            results/rocket_recordings.npz \
            results/ablation_v3_features.csv \
            results/per_item_scores.json \
            results/paper3_split.json \
            results/data_split.json \
            "$REMOTE:$REMOTE_DIR/results/" 2>/dev/null || true
        # Push sensor FM cache if exists
        if [ -d results/sensor_fm_cache ]; then
            rsync -avz --progress \
                -e "ssh -p $PORT" \
                results/sensor_fm_cache/ \
                "$REMOTE:$REMOTE_DIR/results/sensor_fm_cache/"
        fi
        echo "done — cached artifacts uploaded"
        ;;
    "")
        echo "usage: ./gpu.sh <script.py> [args]   deploy + run"
        echo "       ./gpu.sh --pull                fetch results"
        echo "       ./gpu.sh --push-cache           upload cached artifacts"
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
        $SSH "cd $REMOTE_DIR && $PY -u $SCRIPT $*"
        ;;
esac
