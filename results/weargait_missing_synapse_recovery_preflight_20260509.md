# WearGait Missing Synapse Input Recovery Preflight

- Created: `2026-05-09T02:49:30+00:00`
- Mode: `preflight`
- Status: `missing_inputs`
- Data dir: `/home/fiod/pd-imu/data/raw/weargait-pd`
- Project: `syn52540892` (https://www.synapse.org/Synapse:syn52540892/wiki/623751)
- Scientific Data paper: https://www.nature.com/articles/s41597-026-06806-2

## Credential State

- `SYNAPSE_AUTH_TOKEN` present: `False`
- `~/.synapseConfig` present: `False`
- Can attempt download now: `False`

## Missing / Local Status

### control_clinical

- Synapse ID: `syn55105521`
- Expected name: `CONTROLS - Demographic+Clinical - datasetV1.csv`
- Local path: `data/raw/weargait-pd/CONTROLS - Demographic+Clinical - datasetV1.csv`
- Complete: `False`
- Large transfer: `False`
- Synapse probe status: `ok`

### control_csv_folder

- Synapse ID: `syn61370552`
- Expected name: `CSV files`
- Local path: `data/raw/weargait-pd/CONTROL PARTICIPANTS/CSV files`
- Complete: `False`
- Large transfer: `True`
- Synapse probe status: `ok`

- Local CSV count: `0`
- Expected CSV count: `680`

- Synapse CSV children: `680`

### walkway_metrics

- Synapse ID: `syn64589881`
- Expected name: `PKMAS Walkway Gait Metrics - HP+SP.csv`
- Local path: `data/raw/weargait-pd/Walkway-derived metrics/PKMAS Walkway Gait Metrics - HP+SP.csv`
- Complete: `False`
- Large transfer: `False`
- Synapse probe status: `ok`

## Guarded Commands

Dry-run only:

```bash
./gpu.sh scripts/download_weargait_missing_synapse.py --mode preflight
```

Small files only, after credentials are configured:

```bash
./gpu.sh scripts/download_weargait_missing_synapse.py --mode download-small
```

Full recovery, including the 680-file control CSV folder:

```bash
./gpu.sh scripts/download_weargait_missing_synapse.py --mode download-all --confirm-large-control-csvs
```

After full recovery, rerun the non-destructive cache-regeneration probe:

```bash
./gpu.sh audit_ablation_v3_regeneration.py --mode probe --tag <timestamp>
```

This recovery preflight does not promote `results/ablation_v3_features.csv` and does not synthesize a clean cache manifest.

Machine-readable report: `results/weargait_missing_synapse_recovery_preflight_20260509.json`
