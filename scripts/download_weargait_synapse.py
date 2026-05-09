"""Download WearGait-PD raw 22-channel CSVs from Synapse syn61370558.

Mission 2 / slot C activation. Downloads 793 PD CSVs (~16 GB) into
~/pd-imu/data/raw/weargait-pd/PD\\ PARTICIPANTS/CSV\\ files/ (this matches the path
expected by cache_axial_orientation_features.py).

Usage on remote:
  SYNAPSE_AUTH_TOKEN=<token> ~/pd-imu/.venv/bin/python download_weargait_synapse.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import synapseclient
import synapseutils


PD_FOLDER = "syn61370558"  # 'CSV files' folder under the WearGait-PD project
DEMO_FILE = "syn55105530"  # PD demographics CSV (small)
DEST_BASE = Path.home() / "pd-imu" / "data" / "raw" / "weargait-pd"
DEST_PD_CSVS = DEST_BASE / "PD PARTICIPANTS" / "CSV files"


def main() -> int:
    token = os.environ.get("SYNAPSE_AUTH_TOKEN", "").strip()
    if not token:
        print("ERROR: SYNAPSE_AUTH_TOKEN env var not set.", file=sys.stderr)
        return 2
    DEST_PD_CSVS.mkdir(parents=True, exist_ok=True)
    syn = synapseclient.Synapse(skip_checks=True)
    syn.login(authToken=token)
    me = syn.getUserProfile()
    print(f"Logged in as {me['userName']!r}", flush=True)

    # 1. Download demographics (small)
    try:
        ent = syn.get(DEMO_FILE, downloadLocation=str(DEST_BASE), ifcollision="overwrite.local")
        print(f"  demo file: {ent.path}", flush=True)
    except Exception as exc:  # demo is non-critical for slot C extractor
        print(f"  WARN demo download failed: {exc}", flush=True)

    # 2. Download all 793 PD CSVs via syncFromSynapse
    print(f"Starting syncFromSynapse({PD_FOLDER}) → {DEST_PD_CSVS}", flush=True)
    t0 = time.time()
    files = synapseutils.syncFromSynapse(
        syn,
        entity=PD_FOLDER,
        path=str(DEST_PD_CSVS),
        ifcollision="overwrite.local",
        downloadFile=True,
    )
    wall = time.time() - t0
    print(f"syncFromSynapse done in {wall:.0f}s, returned {len(files)} entities", flush=True)

    # 3. Inventory verification
    csvs = sorted(p for p in DEST_PD_CSVS.glob("*.csv"))
    total_bytes = sum(p.stat().st_size for p in csvs)
    print(
        f"INVENTORY: {len(csvs)} CSV files, total {total_bytes / 1e9:.2f} GB",
        flush=True,
    )
    if csvs:
        sample = csvs[0]
        print(f"  first file: {sample.name} ({sample.stat().st_size / 1e6:.2f} MB)", flush=True)

    manifest = {
        "synapse_folder_id": PD_FOLDER,
        "n_files_downloaded": len(csvs),
        "total_bytes": total_bytes,
        "wall_time_s": wall,
        "destination": str(DEST_PD_CSVS),
        "labels_used": False,
        "leakage_status": "clean_by_construction",
    }
    out = DEST_BASE / "synapse_download_manifest.json"
    with open(out, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Manifest: {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
