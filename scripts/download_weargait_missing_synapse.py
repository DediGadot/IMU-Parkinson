#!/usr/bin/env python3
"""Credential-safe recovery helper for missing WearGait-PD raw inputs.

This script is intentionally separate from the historical PD-only downloader.
The default mode performs a dry-run/preflight only: it records the exact Synapse
entities needed to unblock full ablation-v3 cache regeneration, inspects local
missingness, and refuses downloads when credentials are absent.

Full control-CSV recovery is a large transfer and requires
``--confirm-large-control-csvs``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
DATA_DIR = Path(
    os.getenv("WEARGAIT_DATA_DIR", ROOT / "data" / "raw" / "weargait-pd")
)
OUT_JSON = RESULTS / "weargait_missing_synapse_recovery_preflight_20260509.json"
OUT_MD = RESULTS / "weargait_missing_synapse_recovery_preflight_20260509.md"

PROJECT_ID = "syn52540892"
PROJECT_URL = "https://www.synapse.org/Synapse:syn52540892/wiki/623751"
SCIENTIFIC_DATA_URL = "https://www.nature.com/articles/s41597-026-06806-2"

ENTITIES: dict[str, dict[str, Any]] = {
    "control_clinical": {
        "synapse_id": "syn55105521",
        "kind": "file",
        "dest": DATA_DIR / "CONTROLS - Demographic+Clinical - datasetV1.csv",
        "expected_name": "CONTROLS - Demographic+Clinical - datasetV1.csv",
        "required_for": ["ablation_v3_full_regeneration"],
        "large_transfer": False,
    },
    "control_csv_folder": {
        "synapse_id": "syn61370552",
        "kind": "folder",
        "dest": DATA_DIR / "CONTROL PARTICIPANTS" / "CSV files",
        "expected_name": "CSV files",
        "expected_csv_count": 680,
        "required_for": ["ablation_v3_full_regeneration"],
        "large_transfer": True,
    },
    "walkway_metrics": {
        "synapse_id": "syn64589881",
        "kind": "file",
        "dest": DATA_DIR
        / "Walkway-derived metrics"
        / "PKMAS Walkway Gait Metrics - HP+SP.csv",
        "expected_name": "PKMAS Walkway Gait Metrics - HP+SP.csv",
        "required_for": ["ablation_v3_full_regeneration"],
        "large_transfer": False,
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def credential_status() -> dict[str, Any]:
    token_present = bool(os.getenv("SYNAPSE_AUTH_TOKEN", "").strip())
    config_path = Path.home() / ".synapseConfig"
    return {
        "synapse_auth_token_env_present": token_present,
        "synapse_config_present": config_path.exists(),
        "synapse_config_path": str(config_path),
        "can_attempt_download": token_present or config_path.exists(),
    }


def import_synapse() -> tuple[Any | None, Any | None, str | None]:
    try:
        import synapseclient  # type: ignore
        import synapseutils  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on environment
        return None, None, f"{type(exc).__name__}: {exc}"
    return synapseclient, synapseutils, None


def make_synapse(download: bool, creds: dict[str, Any]) -> tuple[Any | None, str | None]:
    synapseclient, _, error = import_synapse()
    if error:
        return None, error
    syn = synapseclient.Synapse(skip_checks=True)
    if not download:
        return syn, None
    token = os.getenv("SYNAPSE_AUTH_TOKEN", "").strip()
    try:
        if token:
            syn.login(authToken=token)
        elif creds["synapse_config_present"]:
            syn.login()
        else:
            return None, "missing_synapse_credentials"
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return syn, None


def local_status(spec: dict[str, Any]) -> dict[str, Any]:
    path = Path(spec["dest"])
    if spec["kind"] == "folder":
        csvs = sorted(path.glob("*.csv")) if path.exists() else []
        expected = spec.get("expected_csv_count")
        complete = bool(path.exists() and (expected is None or len(csvs) >= expected))
        return {
            "path": str(path),
            "relative_path": relative(path),
            "exists": path.exists(),
            "csv_count": len(csvs),
            "expected_csv_count": expected,
            "complete": complete,
        }
    size = path.stat().st_size if path.exists() and path.is_file() else 0
    return {
        "path": str(path),
        "relative_path": relative(path),
        "exists": path.exists(),
        "bytes": size,
        "complete": bool(path.exists() and path.is_file() and size > 0),
    }


def probe_synapse_entity(syn: Any | None, spec: dict[str, Any]) -> dict[str, Any]:
    if syn is None:
        return {"status": "not_probed"}
    out: dict[str, Any] = {"status": "unknown", "synapse_id": spec["synapse_id"]}
    try:
        ent = syn.get(spec["synapse_id"], downloadFile=False)
        out.update(
            {
                "status": "ok",
                "name": getattr(ent, "name", None),
                "class": type(ent).__name__,
            }
        )
    except Exception as exc:
        out.update({"status": "error", "error": f"{type(exc).__name__}: {exc}"})
        return out

    if spec["kind"] == "folder":
        try:
            children = list(
                syn.getChildren(spec["synapse_id"], includeTypes=["folder", "file"])
            )
            csv_children = [c for c in children if str(c.get("name", "")).endswith(".csv")]
            out.update(
                {
                    "children_count": len(children),
                    "csv_children_count": len(csv_children),
                    "first_children": [
                        {"id": c.get("id"), "name": c.get("name"), "type": c.get("type")}
                        for c in children[:10]
                    ],
                }
            )
        except Exception as exc:
            out.update({"children_error": f"{type(exc).__name__}: {exc}"})
    return out


def download_file(syn: Any, spec: dict[str, Any]) -> dict[str, Any]:
    dest = Path(spec["dest"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    ent = syn.get(
        spec["synapse_id"],
        downloadLocation=str(dest.parent),
        ifcollision="overwrite.local",
    )
    wall = time.time() - t0
    path = Path(ent.path)
    if path.name != dest.name and path.exists():
        path.replace(dest)
        path = dest
    return {
        "synapse_id": spec["synapse_id"],
        "downloaded_path": str(path),
        "wall_time_s": wall,
        "bytes": path.stat().st_size if path.exists() else 0,
    }


def download_folder(syn: Any, synapseutils: Any, spec: dict[str, Any]) -> dict[str, Any]:
    dest = Path(spec["dest"])
    dest.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    files = synapseutils.syncFromSynapse(
        syn,
        entity=spec["synapse_id"],
        path=str(dest),
        ifcollision="overwrite.local",
        downloadFile=True,
    )
    wall = time.time() - t0
    csvs = sorted(dest.glob("*.csv"))
    return {
        "synapse_id": spec["synapse_id"],
        "downloaded_path": str(dest),
        "sync_entities_returned": len(files),
        "csv_count": len(csvs),
        "wall_time_s": wall,
    }


def build_report(mode: str, args: argparse.Namespace) -> dict[str, Any]:
    creds = credential_status()
    synapseclient, synapseutils, import_error = import_synapse()
    download_requested = mode in {"download-small", "download-all"}

    syn = None
    login_error = None
    if synapseclient is not None:
        syn, login_error = make_synapse(download_requested, creds)
        if not download_requested and login_error:
            syn = None

    entities: dict[str, Any] = {}
    missing: list[str] = []
    for name, spec in ENTITIES.items():
        local = local_status(spec)
        if not local["complete"]:
            missing.append(name)
        entities[name] = {
            "synapse_id": spec["synapse_id"],
            "kind": spec["kind"],
            "expected_name": spec["expected_name"],
            "large_transfer": spec["large_transfer"],
            "required_for": spec["required_for"],
            "local": local,
            "synapse_probe": probe_synapse_entity(syn, spec),
        }

    status = "complete" if not missing else "missing_inputs"
    downloads: dict[str, Any] = {}
    if import_error:
        status = "blocked_missing_synapseclient"
    elif download_requested and not creds["can_attempt_download"]:
        status = "blocked_missing_synapse_credentials"
    elif download_requested and login_error:
        status = "blocked_synapse_login_failed"
    elif mode == "download-all" and not args.confirm_large_control_csvs:
        status = "blocked_large_download_requires_confirm_flag"
    elif mode == "download-small" and syn is not None:
        for name in ("control_clinical", "walkway_metrics"):
            if not entities[name]["local"]["complete"]:
                downloads[name] = download_file(syn, ENTITIES[name])
        status = "download_small_complete"
    elif mode == "download-all" and syn is not None and synapseutils is not None:
        for name in ("control_clinical", "walkway_metrics"):
            if not entities[name]["local"]["complete"]:
                downloads[name] = download_file(syn, ENTITIES[name])
        if not entities["control_csv_folder"]["local"]["complete"]:
            downloads["control_csv_folder"] = download_folder(
                syn, synapseutils, ENTITIES["control_csv_folder"]
            )
        status = "download_all_complete"

    # Refresh local status after any downloads.
    if downloads:
        missing = []
        for name, spec in ENTITIES.items():
            entities[name]["local_after"] = local_status(spec)
            if not entities[name]["local_after"]["complete"]:
                missing.append(name)
        if missing and status.startswith("download_"):
            status = "download_incomplete"

    return {
        "created_at_utc": utc_now(),
        "mode": mode,
        "status": status,
        "data_dir": str(DATA_DIR),
        "project": {
            "synapse_id": PROJECT_ID,
            "url": PROJECT_URL,
            "scientific_data_url": SCIENTIFIC_DATA_URL,
        },
        "credential_status": creds,
        "synapseclient_import_error": import_error,
        "synapse_login_error": login_error,
        "missing": missing,
        "entities": entities,
        "downloads": downloads,
        "guardrails": {
            "preflight_downloads": False,
            "large_control_csv_download_requires_confirm_flag": True,
            "does_not_promote_ablation_v3_cache": True,
            "next_after_full_restore": "./gpu.sh audit_ablation_v3_regeneration.py --mode probe --tag <timestamp>",
        },
    }


def write_outputs(report: dict[str, Any]) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, indent=2, default=str) + "\n")
    lines = [
        "# WearGait Missing Synapse Input Recovery Preflight",
        "",
        f"- Created: `{report['created_at_utc']}`",
        f"- Mode: `{report['mode']}`",
        f"- Status: `{report['status']}`",
        f"- Data dir: `{report['data_dir']}`",
        f"- Project: `{PROJECT_ID}` ({PROJECT_URL})",
        f"- Scientific Data paper: {SCIENTIFIC_DATA_URL}",
        "",
        "## Credential State",
        "",
        f"- `SYNAPSE_AUTH_TOKEN` present: `{report['credential_status']['synapse_auth_token_env_present']}`",
        f"- `~/.synapseConfig` present: `{report['credential_status']['synapse_config_present']}`",
        f"- Can attempt download now: `{report['credential_status']['can_attempt_download']}`",
        "",
        "## Missing / Local Status",
        "",
    ]
    for name, payload in report["entities"].items():
        local = payload.get("local_after") or payload["local"]
        lines.extend(
            [
                f"### {name}",
                "",
                f"- Synapse ID: `{payload['synapse_id']}`",
                f"- Expected name: `{payload['expected_name']}`",
                f"- Local path: `{local['relative_path']}`",
                f"- Complete: `{local['complete']}`",
                f"- Large transfer: `{payload['large_transfer']}`",
                f"- Synapse probe status: `{payload['synapse_probe'].get('status')}`",
                "",
            ]
        )
        if "csv_count" in local:
            lines.extend(
                [
                    f"- Local CSV count: `{local['csv_count']}`",
                    f"- Expected CSV count: `{local.get('expected_csv_count')}`",
                    "",
                ]
            )
        if payload["synapse_probe"].get("csv_children_count") is not None:
            lines.extend(
                [
                    f"- Synapse CSV children: `{payload['synapse_probe']['csv_children_count']}`",
                    "",
                ]
            )

    lines.extend(
        [
            "## Guarded Commands",
            "",
            "Dry-run only:",
            "",
            "```bash",
            "./gpu.sh scripts/download_weargait_missing_synapse.py --mode preflight",
            "```",
            "",
            "Small files only, after credentials are configured:",
            "",
            "```bash",
            "./gpu.sh scripts/download_weargait_missing_synapse.py --mode download-small",
            "```",
            "",
            "Full recovery, including the 680-file control CSV folder:",
            "",
            "```bash",
            "./gpu.sh scripts/download_weargait_missing_synapse.py --mode download-all --confirm-large-control-csvs",
            "```",
            "",
            "After full recovery, rerun the non-destructive cache-regeneration probe:",
            "",
            "```bash",
            "./gpu.sh audit_ablation_v3_regeneration.py --mode probe --tag <timestamp>",
            "```",
            "",
            "This recovery preflight does not promote `results/ablation_v3_features.csv` and does not synthesize a clean cache manifest.",
            "",
            f"Machine-readable report: `{relative(OUT_JSON)}`",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines))
    print(json.dumps({"status": report["status"], "missing": report["missing"]}, indent=2))
    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("preflight", "download-small", "download-all"),
        default="preflight",
    )
    parser.add_argument(
        "--confirm-large-control-csvs",
        action="store_true",
        help="Required for --mode download-all because the control CSV folder has 680 files.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(args.mode, args)
    write_outputs(report)
    if report["status"].startswith("blocked"):
        return 2
    if report["status"] in {"download_incomplete", "missing_inputs"}:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
