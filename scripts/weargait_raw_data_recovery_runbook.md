# WearGait-PD Raw Data Recovery Runbook

This runbook is for recovering the missing raw WearGait-PD inputs that block a
clean regeneration of `results/ablation_v3_features.csv`. It is not a model
result, not a pre-registration, and not permission to promote the frozen V2 cache.

## Current Boundary

The non-destructive regeneration probe is blocked because the current remote has
PD clinical data and PD raw CSVs, but it is missing three inputs needed to
reproduce the full 178-subject V2 cache:

| Input | Synapse ID | Expected local path | Transfer class |
|---|---|---|---|
| Controls clinical CSV | `syn55105521` | `data/raw/weargait-pd/CONTROLS - Demographic+Clinical - datasetV1.csv` | small file |
| Controls raw CSV folder | `syn61370552` | `data/raw/weargait-pd/CONTROL PARTICIPANTS/CSV files` | large folder, 680 CSVs |
| Walkway metrics CSV | `syn64589881` | `data/raw/weargait-pd/Walkway-derived metrics/PKMAS Walkway Gait Metrics - HP+SP.csv` | small file |

Parent project: `syn52540892`

Project page: https://www.synapse.org/Synapse:syn52540892/wiki/623751

Reference paper: https://www.nature.com/articles/s41597-026-06806-2

Latest dry-run artifact:

- `results/weargait_missing_synapse_recovery_preflight_20260509.json`
- `results/weargait_missing_synapse_recovery_preflight_20260509.md`

Current dry-run status is `missing_inputs`; no `SYNAPSE_AUTH_TOKEN` or
`~/.synapseConfig` was present when the report was written.

## Guardrails

- Do not run `download-small` or `download-all` until the user has a valid
  Synapse account and credentials on the machine where `gpu.sh` executes.
- Do not bypass a Synapse access prompt, DUA prompt, or project term prompt. If
  Synapse denies access or asks for approval, stop and request access through the
  Synapse UI.
- Do not run `download-all` without an explicit large-transfer confirmation:
  `--confirm-large-control-csvs`.
- Do not overwrite or promote `results/ablation_v3_features.csv` from this
  runbook. The downloader only restores raw inputs.
- Do not synthesize a clean cache manifest after raw-input recovery alone. A
  non-destructive regeneration probe must succeed first.
- Do not start a new T1/T3 model run from this branch. The next code action
  after full raw-input recovery is the regeneration probe below.

## Sources For Client Setup

Synapse currently supports Personal Access Token authentication through
`SYNAPSE_AUTH_TOKEN` or profile/config based authentication via
`~/.synapseConfig`. The Python/CLI docs also document bulk download through
`syncFromSynapse`.

- Authentication docs: https://python-docs.synapse.org/en/v4.8.0/tutorials/authentication/
- Client docs: https://python-docs.synapse.org/en/stable/reference/client/
- Programmatic download docs: https://help.synapse.org/docs/Downloading-Data-Programmatically.2003796248.html

## Step 1 - Confirm Local State

This command is dry-run only. It probes known Synapse entity metadata and local
missingness, then exits nonzero while inputs remain missing.

```bash
cd /home/fiod/medical
./gpu.sh scripts/download_weargait_missing_synapse.py --mode preflight
./gpu.sh --pull
```

Expected before recovery:

- `control_clinical` incomplete.
- `control_csv_folder` incomplete, with expected CSV count `680`.
- `walkway_metrics` incomplete.
- `results/ablation_v3_features.csv` unchanged.

## Step 2 - Configure Synapse Credentials

Use one of these credential paths on the remote machine. Do not commit tokens or
paste them into tracked files.

Option A, token environment variable for the shell session:

```bash
export SYNAPSE_AUTH_TOKEN='<paste-personal-access-token>'
python - <<'PY'
import os
import synapseclient
synapseclient.login(authToken=os.environ["SYNAPSE_AUTH_TOKEN"])
PY
```

Option B, profile/config authentication:

```bash
python - <<'PY'
import synapseclient
syn = synapseclient.Synapse()
syn.login()
PY
test -f ~/.synapseConfig
```

If the project page requests access or terms acceptance for `syn52540892`, stop
and complete that request in the Synapse UI before attempting a download.

## Step 3 - Download Small Files First

After credentials exist, recover only the two small files:

```bash
cd /home/fiod/medical
./gpu.sh scripts/download_weargait_missing_synapse.py --mode download-small
./gpu.sh --pull
```

Expected after small-file recovery:

- `control_clinical` complete.
- `walkway_metrics` complete.
- `control_csv_folder` still incomplete.
- No regenerated V2 cache is written.

Stop if either small file has a different name, zero bytes, or cannot be
downloaded under the accepted Synapse terms.

## Step 4 - Download The Control CSV Folder

The control CSV folder is the large transfer. It is allowed only after the user
has explicitly accepted the size and storage cost.

```bash
cd /home/fiod/medical
./gpu.sh scripts/download_weargait_missing_synapse.py --mode download-all --confirm-large-control-csvs
./gpu.sh --pull
```

Expected after full recovery:

- `CONTROL PARTICIPANTS/CSV files` exists.
- Local control CSV count is at least `680`.
- `control_clinical` and `walkway_metrics` remain complete.
- No model or lockbox has run.

Stop if the local control CSV count is below `680`, if Synapse reports partial
download failures, or if file names do not match the preflight child listing.

## Step 5 - Re-run The Preflight

```bash
cd /home/fiod/medical
./gpu.sh scripts/download_weargait_missing_synapse.py --mode preflight
./gpu.sh --pull
```

The preflight should report `status=complete` only when all three inputs are
present. If it still reports missing inputs, do not proceed.

## Step 6 - Run The Non-Destructive Regeneration Probe

Only after the preflight is complete, run the probe that writes to a timestamped
candidate path and leaves the frozen cache untouched:

```bash
cd /home/fiod/medical
./gpu.sh audit_ablation_v3_regeneration.py --mode probe --tag raw_restore_20260509
./gpu.sh --pull
```

Promotion remains blocked unless the probe proves all of the following:

- full input status is complete;
- the frozen `results/ablation_v3_features.csv` SHA is unchanged during the probe;
- a regenerated candidate cache is produced at a separate path;
- the regenerated cache can be compared to the frozen cache;
- any new manifest records script, command, git SHA, raw-data hash, labels used,
  fold scope, cohort statistics scope, normalization scope, leakage status, and
  rationale.

## Stop Conditions

Stop and do not patch around the issue if any of these happen:

- Synapse credentials are absent or rejected.
- Synapse asks for project access, a DUA, or terms that have not been accepted.
- A named Synapse entity is unavailable or resolves to an unexpected file.
- The control CSV folder returns fewer than `680` CSVs.
- The frozen V2 cache changes during any recovery or probe command.
- The regeneration probe cannot run without modifying historical scripts in a
  way that changes model behavior.
- A clean manifest cannot be justified from regenerated artifacts.

## Completion State

This branch is complete only when the regeneration probe writes a passing report
showing full raw input recovery. Until then, `ablation_v3_features.csv` remains a
diagnostic/provenance-caveated cache and must not be described as
cache-manifest-clean.
