# Manual Cache Backfill Evidence Audit - 2026-05-09

This non-mutating audit inspects the five missing-manifest artifacts that the origin audit classified as manual backfill candidates.
It does not create any sidecar manifests.

## Summary

- Manual candidates audited: `5`
- `leave_missing_no_patch`: `5`
- Remote recovery probe return code: `0`
- Remote recovery probe output: see section below

## Decisions

- `results/hc_ssl_subj_embeddings.csv` - `leave_missing_no_patch`; producer `cache_hc_ssl_embeddings.py`; git match `d281a0e`; shape `178x769`; source status `results/rocket_recordings.npz=broken symlink`. No exact invocation was found, and narrative context says 80 epochs while the committed producer default is 50 epochs.
- `results/joints_v2_subj.csv` - `leave_missing_no_patch`; producer `cache_joints_v2.py`; git match `d281a0e`; shape `100x990`; source status `data/raw/weargait-pd/PD PARTICIPANTS/CSV files=missing`. No exact --csv_dir/--out_strides/--out_subj invocation was found.
- `results/moment_subj_embeddings.csv` - `leave_missing_no_patch`; producer `cache_moment_embeddings.py`; git match `d281a0e`; shape `178x2305`; source status `results/rocket_recordings.npz=broken symlink`. No exact invocation/runtime log was found.
- `results/stride_locked_subj.csv` - `leave_missing_no_patch`; producer `cache_stride_locked.py`; git match `d281a0e`; shape `100x1174`; source status `data/raw/weargait-pd/PD PARTICIPANTS/CSV files=missing`. No exact --csv_dir/--out invocation was found.
- `results/tug_transition_features.csv` - `leave_missing_no_patch`; producer `cache_tug_transition_features.py`; git match `d281a0e`; shape `176x422`; source status `results/rocket_recordings.npz=broken symlink`. No exact invocation/runtime log was found.

## Remote Recovery Probe

- `REMOTE_ROOT /home/fiod/pd-imu`
- `BROKEN_SYMLINK results/rocket_recordings.npz -> /home/fiod/medical/results/results/rocket_recordings.npz 56 bytes mtime=2026-04-28 13:26:14.356989943 +0300`
- `MISSING results/hc_ssl_subj_embeddings.csv`
- `MISSING results/moment_subj_embeddings.csv`
- `MISSING results/joints_v2_subj.csv`
- `MISSING results/stride_locked_subj.csv`
- `MISSING results/tug_transition_features.csv`
- `MISSING results/cache_features.log`

## Policy Decision

All five artifacts remain diagnostic-only. Backfilling a clean manifest would require concrete exact command/runtime evidence and recoverable source-input hashes; those fields are not safely inferable from committed producer scripts or narrative notes.

Machine-readable report: `results/manual_cache_backfill_evidence_20260509.json`
