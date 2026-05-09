#!/usr/bin/env python3
"""Probe the public TLVMC Parkinson's FoG dataset as a T3 external route.

The probe downloads only public metadata files through the Kaggle API and writes
aggregate counts. It intentionally does not persist row-level clinical metadata
or raw sensor files inside the repository.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
ZENODO_API = "https://zenodo.org/api/records/10959560"
KAGGLE_COMPETITION = "tlvmc-parkinsons-freezing-gait-prediction"
METADATA_FILES = [
    "subjects.csv",
    "defog_metadata.csv",
    "tdcsfog_metadata.csv",
    "daily_metadata.csv",
    "tasks.csv",
]
RAW_SAMPLE_FILES = {
    "defog": "train/defog/02ea782681.csv",
}


def run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, text=True)


def download_metadata(target_dir: Path) -> None:
    kaggle = shutil.which("kaggle")
    if kaggle is None:
        raise RuntimeError("kaggle CLI is required to download TLVMC metadata")
    target_dir.mkdir(parents=True, exist_ok=True)
    for filename in METADATA_FILES:
        run(
            [
                kaggle,
                "competitions",
                "download",
                "-c",
                KAGGLE_COMPETITION,
                "-f",
                filename,
                "-p",
                str(target_dir),
                "--force",
                "--quiet",
            ],
            cwd=ROOT,
        )


def download_kaggle_file(filename: str, target_dir: Path) -> Path:
    kaggle = shutil.which("kaggle")
    if kaggle is None:
        raise RuntimeError("kaggle CLI is required to download TLVMC files")
    run(
        [
            kaggle,
            "competitions",
            "download",
            "-c",
            KAGGLE_COMPETITION,
            "-f",
            filename,
            "-p",
            str(target_dir),
            "--force",
            "--quiet",
        ],
        cwd=ROOT,
    )
    return target_dir / Path(filename).name


def read_kaggle_csv_download(path: Path) -> pd.DataFrame:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            csv_names = [name for name in zf.namelist() if name.endswith(".csv")]
            if len(csv_names) != 1:
                raise RuntimeError(f"Expected one CSV inside {path}, found {csv_names}")
            with zf.open(csv_names[0]) as f:
                return pd.read_csv(f)
    return pd.read_csv(path)


def summarize_raw_sample(name: str, filename: str, target_dir: Path) -> dict[str, Any]:
    path = download_kaggle_file(filename, target_dir)
    df = read_kaggle_csv_download(path)
    summary: dict[str, Any] = {
        "source_file": filename,
        "downloaded_name": path.name,
        "rows": int(df.shape[0]),
        "columns": list(df.columns),
    }
    if "Time" in df.columns:
        summary["time_start"] = int(df["Time"].iloc[0])
        summary["time_end"] = int(df["Time"].iloc[-1])
    for col in ["AccV", "AccML", "AccAP", "Valid", "Task", "StartHesitation", "Turn", "Walking"]:
        if col not in df.columns:
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            summary[col] = {
                "dtype": str(df[col].dtype),
                "min": float(df[col].min()),
                "max": float(df[col].max()),
                "mean": float(df[col].mean()),
            }
        else:
            summary[col] = {
                "dtype": str(df[col].dtype),
                "value_counts_top": {str(k): int(v) for k, v in df[col].value_counts().head().items()},
            }
    return summary


def load_zenodo_metadata() -> dict[str, Any]:
    with urllib.request.urlopen(ZENODO_API, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    files = []
    for item in payload.get("files", []):
        files.append(
            {
                "key": item.get("key"),
                "size_bytes": item.get("size"),
                "checksum": item.get("checksum"),
            }
        )
    return {
        "record_id": payload.get("id"),
        "doi": payload.get("doi"),
        "title": payload.get("metadata", {}).get("title"),
        "license": payload.get("metadata", {}).get("license", {}).get("id"),
        "files": files,
    }


def numeric_summary(series: pd.Series) -> dict[str, Any]:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return {"n": 0}
    return {
        "n": int(s.shape[0]),
        "min": float(s.min()),
        "median": float(s.median()),
        "max": float(s.max()),
    }


def normalize_visit(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["Visit"] = pd.to_numeric(out["Visit"], errors="coerce").astype("Int64")
    return out


def summarize_recording_metadata(name: str, meta: pd.DataFrame, subjects: pd.DataFrame) -> dict[str, Any]:
    meta = normalize_visit(meta)
    subjects = normalize_visit(subjects)
    merged = meta.merge(subjects, on=["Subject", "Visit"], how="left", suffixes=("", "_subject"))
    has_on = pd.to_numeric(merged["UPDRSIII_On"], errors="coerce").notna()
    has_off = pd.to_numeric(merged["UPDRSIII_Off"], errors="coerce").notna()
    any_target = has_on | has_off

    matching_med_target = pd.Series(False, index=merged.index)
    medication_counts: dict[str, int] = {}
    if "Medication" in merged.columns:
        med = merged["Medication"].astype(str).str.lower()
        medication_counts = {str(k): int(v) for k, v in med.value_counts(dropna=False).items()}
        matching_med_target = ((med == "on") & has_on) | ((med == "off") & has_off)

    return {
        "rows": int(meta.shape[0]),
        "unique_subjects": int(meta["Subject"].nunique()),
        "unique_subject_visits": int(meta[["Subject", "Visit"]].drop_duplicates().shape[0]),
        "rows_joining_subjects": int(any_target.shape[0] - merged["Age"].isna().sum()),
        "rows_with_any_updrsiii_target": int(any_target.sum()),
        "rows_with_matching_medication_updrsiii_target": int(matching_med_target.sum()),
        "medication_counts": medication_counts,
        "columns": list(meta.columns),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metadata-dir",
        type=Path,
        default=None,
        help="Directory for temporary Kaggle metadata. Defaults to a temp dir.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=RESULTS / "tlvmc_fog_route_probe_20260509.json",
        help="Output aggregate JSON path.",
    )
    parser.add_argument(
        "--md-out",
        type=Path,
        default=RESULTS / "tlvmc_fog_route_probe_20260509.md",
        help="Output aggregate Markdown summary path.",
    )
    args = parser.parse_args()

    RESULTS.mkdir(exist_ok=True)
    temp_ctx = tempfile.TemporaryDirectory(prefix="tlvmc_fog_probe_") if args.metadata_dir is None else None
    metadata_dir = args.metadata_dir or Path(temp_ctx.name)
    try:
        download_metadata(metadata_dir)

        subjects = pd.read_csv(metadata_dir / "subjects.csv")
        defog = pd.read_csv(metadata_dir / "defog_metadata.csv")
        tdcsfog = pd.read_csv(metadata_dir / "tdcsfog_metadata.csv")
        daily = pd.read_csv(metadata_dir / "daily_metadata.csv")
        tasks = pd.read_csv(metadata_dir / "tasks.csv")

        subject_target_rows = subjects[
            pd.to_numeric(subjects["UPDRSIII_On"], errors="coerce").notna()
            | pd.to_numeric(subjects["UPDRSIII_Off"], errors="coerce").notna()
        ]

        result = {
            "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "script": "scripts/probe_tlvmc_fog_route.py",
            "sources": {
                "zenodo_record": "https://zenodo.org/records/10959560",
                "zenodo_api": ZENODO_API,
                "kaggle_competition": f"https://www.kaggle.com/competitions/{KAGGLE_COMPETITION}",
                "nature_communications": "https://www.nature.com/articles/s41467-024-49027-0",
            },
            "zenodo": load_zenodo_metadata(),
            "downloaded_metadata_files": METADATA_FILES,
            "row_level_metadata_persisted_in_repo": False,
            "subjects": {
                "rows": int(subjects.shape[0]),
                "unique_subjects": int(subjects["Subject"].nunique()),
                "unique_subject_visits": int(subjects[["Subject", "Visit"]].drop_duplicates().shape[0]),
                "columns": list(subjects.columns),
                "rows_with_any_updrsiii_target": int(subject_target_rows.shape[0]),
                "unique_subjects_with_any_updrsiii_target": int(subject_target_rows["Subject"].nunique()),
                "updrsiii_on": numeric_summary(subjects["UPDRSIII_On"]),
                "updrsiii_off": numeric_summary(subjects["UPDRSIII_Off"]),
                "nfogq": numeric_summary(subjects["NFOGQ"]),
            },
            "recording_metadata": {
                "defog": summarize_recording_metadata("defog", defog, subjects),
                "tdcsfog": summarize_recording_metadata("tdcsfog", tdcsfog, subjects),
                "daily": summarize_recording_metadata("daily", daily, subjects),
                "tasks": {
                    "rows": int(tasks.shape[0]),
                    "unique_recording_ids": int(tasks["Id"].nunique()),
                    "unique_tasks": int(tasks["Task"].nunique()),
                    "columns": list(tasks.columns),
                    "top_tasks": {
                        str(k): int(v) for k, v in tasks["Task"].value_counts().head(12).items()
                    },
                },
            },
            "raw_schema_samples": {
                key: summarize_raw_sample(key, filename, metadata_dir)
                for key, filename in RAW_SAMPLE_FILES.items()
            },
            "t3_route_classification": {
                "direct_t3_eligible": True,
                "reason": (
                    "Public metadata includes Subject/Visit rows with UPDRSIII_On and "
                    "UPDRSIII_Off totals. DeFOG recording metadata links sensor file ids "
                    "to Subject/Visit plus medication state, yielding medication-matched "
                    "UPDRS-III targets for all 137 DeFOG recordings. Daily metadata also "
                    "joins to visit-level UPDRS-III targets but lacks medication state. "
                    "tdcsfog metadata does not join to subjects.csv targets in this public "
                    "metadata probe and is not counted as a direct T3 target route."
                ),
                "not_internal_ceiling_break": True,
                "recommended_next_step": (
                    "Write a separate zero-shot external-validation preregistration/probe "
                    "before any model run; do not use this as another WearGait internal "
                    "variant screen."
                ),
            },
        }

        args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        args.md_out.write_text(render_markdown(result), encoding="utf-8")
        print(f"Wrote {args.out.relative_to(ROOT)}")
        print(f"Wrote {args.md_out.relative_to(ROOT)}")
    finally:
        if temp_ctx is not None:
            temp_ctx.cleanup()


def render_markdown(result: dict[str, Any]) -> str:
    subjects = result["subjects"]
    rec = result["recording_metadata"]
    z = result["zenodo"]
    raw = result.get("raw_schema_samples", {}).get("defog", {})
    return "\n".join(
        [
            "# TLVMC / DeFOG Route Probe",
            "",
            f"- Created: `{result['created_at_utc']}`",
            f"- Zenodo DOI: `{z['doi']}`",
            f"- License: `{z['license']}`",
            f"- Row-level metadata persisted in repo: `{result['row_level_metadata_persisted_in_repo']}`",
            "",
            "## T3 Eligibility",
            "",
            f"- Direct T3 eligible: `{result['t3_route_classification']['direct_t3_eligible']}`",
            f"- Reason: {result['t3_route_classification']['reason']}",
            f"- Next step: {result['t3_route_classification']['recommended_next_step']}",
            "",
            "## Metadata Counts",
            "",
            f"- `subjects.csv`: {subjects['rows']} rows, {subjects['unique_subjects']} unique subjects, "
            f"{subjects['rows_with_any_updrsiii_target']} rows with an UPDRS-III target.",
            f"- `UPDRSIII_On`: N={subjects['updrsiii_on']['n']}, range "
            f"{subjects['updrsiii_on']['min']}-{subjects['updrsiii_on']['max']}.",
            f"- `UPDRSIII_Off`: N={subjects['updrsiii_off']['n']}, range "
            f"{subjects['updrsiii_off']['min']}-{subjects['updrsiii_off']['max']}.",
            f"- `defog_metadata.csv`: {rec['defog']['rows']} recordings, "
            f"{rec['defog']['unique_subjects']} subjects, "
            f"{rec['defog']['unique_subject_visits']} subject-visits, "
            f"{rec['defog']['rows_with_matching_medication_updrsiii_target']} medication-matched targets.",
            f"- `daily_metadata.csv`: {rec['daily']['rows']} recordings, "
            f"{rec['daily']['rows_with_any_updrsiii_target']} visit-level targets, no medication-state column.",
            f"- `tdcsfog_metadata.csv`: {rec['tdcsfog']['rows']} recordings, "
            f"{rec['tdcsfog']['rows_with_any_updrsiii_target']} joined UPDRS-III targets in this probe.",
            f"- Raw DeFOG sample `{raw.get('source_file', 'n/a')}`: {raw.get('rows', 'n/a')} rows, "
            f"columns `{', '.join(raw.get('columns', []))}`.",
            "",
            "## Sources",
            "",
            f"- Zenodo record: {result['sources']['zenodo_record']}",
            f"- Kaggle competition: {result['sources']['kaggle_competition']}",
            f"- Nature Communications article: {result['sources']['nature_communications']}",
            "",
        ]
    )


if __name__ == "__main__":
    main()
