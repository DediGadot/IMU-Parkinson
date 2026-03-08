"""
Dataset loaders for PD-IMU project.
Handles PhysioNet Gait-PD, PADS, mPower, and CIS-PD formats.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Iterator
import wfdb
import re


@dataclass(frozen=True)
class IMUSegment:
    """Immutable container for one segment of IMU data with labels."""
    subject_id: str
    accel_xyz: np.ndarray       # (N, 3) accelerometer
    gyro_xyz: Optional[np.ndarray]  # (N, 3) gyroscope, None if unavailable
    fs: float                    # sampling frequency
    label_hy: Optional[int]      # Hoehn and Yahr stage (1-5)
    label_updrs: Optional[float]  # MDS-UPDRS score
    label_group: str             # "pd" or "control"
    metadata: dict               # any additional info


def load_gaitpdb(data_dir: str) -> list[IMUSegment]:
    """Load PhysioNet Gait in Parkinson Disease dataset.

    This dataset uses vertical ground reaction force from foot sensors,
    NOT IMU. We use it for gait timing ground truth.

    File naming: {study}{subject}{condition}.dat
    Studies: Ga (Garcia), Ju (Jursaitis), Si (Silveira)
    """
    data_path = Path(data_dir)
    segments = []

    hea_files = sorted(data_path.rglob("*.hea"))

    for hea_file in hea_files:
        try:
            record_name = hea_file.stem
            record = wfdb.rdrecord(str(hea_file.parent / record_name))

            signals = record.p_signal  # (N, num_channels)
            fs = record.fs
            study = record_name[:2]

            comments = record.comments if record.comments else []
            is_pd = any(
                "parkinson" in c.lower() or "pd" in c.lower()
                for c in comments
            )

            hy_stage = None
            for comment in comments:
                if "h&y" in comment.lower() or "hoehn" in comment.lower():
                    match = re.search(r"(\d\.?\d?)", comment)
                    if match:
                        hy_stage = int(float(match.group(1)))

            accel_proxy = np.column_stack([
                signals.mean(axis=1),
                np.zeros(len(signals)),
                np.zeros(len(signals)),
            ])

            segments.append(IMUSegment(
                subject_id=f"{study}_{record_name}",
                accel_xyz=accel_proxy,
                gyro_xyz=None,
                fs=float(fs),
                label_hy=hy_stage,
                label_updrs=None,
                label_group="pd" if is_pd else "control",
                metadata={
                    "study": study,
                    "record_name": record_name,
                    "num_channels": signals.shape[1],
                    "comments": comments,
                    "source": "gaitpdb",
                },
            ))
        except Exception as e:
            print(f"Warning: Failed to load {hea_file}: {e}")
            continue

    return segments


def load_pads(data_dir: str) -> list[IMUSegment]:
    """Load PADS (Parkinson Disease Smartwatch Dataset).

    Expected format: CSV files with accelerometer + gyroscope from smartwatch.
    """
    data_path = Path(data_dir)
    segments = []

    csv_files = sorted(data_path.rglob("*.csv"))

    for csv_file in csv_files:
        try:
            df = pd.read_csv(csv_file)

            accel_cols = [c for c in df.columns if "accel" in c.lower() or "acc" in c.lower()]
            gyro_cols = [c for c in df.columns if "gyro" in c.lower()]

            if len(accel_cols) >= 3:
                accel_xyz = df[accel_cols[:3]].values
            elif {"x", "y", "z"}.issubset(set(df.columns)):
                accel_xyz = df[["x", "y", "z"]].values
            else:
                print(f"Warning: Cannot find accel columns in {csv_file}")
                continue

            gyro_xyz = df[gyro_cols[:3]].values if len(gyro_cols) >= 3 else None

            if "timestamp" in df.columns or "time" in df.columns:
                time_col = "timestamp" if "timestamp" in df.columns else "time"
                times = df[time_col].values
                fs = 1.0 / np.median(np.diff(times)) if len(times) > 1 else 50.0
            else:
                fs = 50.0

            subject_id = csv_file.stem

            segments.append(IMUSegment(
                subject_id=subject_id,
                accel_xyz=accel_xyz,
                gyro_xyz=gyro_xyz,
                fs=fs,
                label_hy=None,
                label_updrs=None,
                label_group="pd",
                metadata={
                    "source": "pads",
                    "file": str(csv_file),
                    "columns": list(df.columns),
                },
            ))
        except Exception as e:
            print(f"Warning: Failed to load {csv_file}: {e}")
            continue

    return segments


def window_segments(
    segments: list[IMUSegment],
    window_sec: float = 10.0,
    overlap: float = 0.5,
) -> Iterator[IMUSegment]:
    """Sliding window over IMU segments.

    Args:
        segments: List of IMU segments
        window_sec: Window duration in seconds
        overlap: Overlap fraction (0-1)

    Yields:
        New IMUSegment for each window (immutable, no mutation)
    """
    for seg in segments:
        window_samples = int(window_sec * seg.fs)
        step_samples = int(window_samples * (1 - overlap))

        n_samples = len(seg.accel_xyz)

        for start in range(0, n_samples - window_samples + 1, step_samples):
            end = start + window_samples

            yield IMUSegment(
                subject_id=seg.subject_id,
                accel_xyz=seg.accel_xyz[start:end],
                gyro_xyz=seg.gyro_xyz[start:end] if seg.gyro_xyz is not None else None,
                fs=seg.fs,
                label_hy=seg.label_hy,
                label_updrs=seg.label_updrs,
                label_group=seg.label_group,
                metadata={**seg.metadata, "window_start": start, "window_end": end},
            )
