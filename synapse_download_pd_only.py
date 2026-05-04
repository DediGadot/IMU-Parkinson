"""Download ONLY the PD CSV folder + PD demographics CSV from WearGait-PD.

Skips:
- CONTROL PARTICIPANTS (HC, ~14 GB) — dropped from all our deployment pipelines
- PD PARTICIPANTS/MAT file (7.6 GB) — we use CSVs, not MATs
- Real-world context tasks, walkway-derived metrics — not used in current pipeline

Targets ~15 GB total: PD CSVs (14.7 GB) + clinical metadata (~1 MB).

Usage: SYNAPSE_TOKEN=... python3 synapse_download_pd_only.py
"""
import os
import sys
import time
from pathlib import Path

import synapseclient
import synapseutils

OUT_ROOT = Path("/root/pd-imu/data/raw/weargait-pd")
TARGETS = [
    ("syn61370558", "PD PARTICIPANTS/CSV files"),  # ~14.7 GB
    ("syn55105530", "PD - Demographic+Clinical - datasetV1.csv"),  # ~1 MB
]


def main():
    token = os.environ.get("SYNAPSE_TOKEN")
    if not token:
        print("ERROR: SYNAPSE_TOKEN env var not set", file=sys.stderr)
        sys.exit(1)

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    syn = synapseclient.Synapse()
    syn.login(authToken=token)
    print(f"Logged in. Target: {OUT_ROOT}")

    t0 = time.time()
    total_files = 0
    for syn_id, rel_path in TARGETS:
        out_path = OUT_ROOT / rel_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"\n=== Fetching {syn_id} → {out_path} ===")
        files = synapseutils.syncFromSynapse(syn, syn_id, path=str(out_path.parent if out_path.suffix else out_path))
        total_files += len(files)
        elapsed = time.time() - t0
        print(f"  {len(files)} files synced. Cumulative: {total_files} files, {elapsed:.0f}s elapsed")

    print(f"\n=== DONE ===")
    print(f"Total files: {total_files}")
    print(f"Wall-clock: {(time.time() - t0) / 60:.1f} min")
    # Disk check
    os.system(f"du -sh {OUT_ROOT}")


if __name__ == "__main__":
    main()
