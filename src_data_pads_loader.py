"""
PADS (Parkinson's Disease Smartwatch Dataset) loader.

Dataset structure:
  pads/physionet.org/files/parkinsons-disease-smartwatch/1.0.0/
    movement/
      observation_NNN.json         # metadata per subject
      timeseries/
        NNN_TaskName_LeftWrist.txt  # 7 cols: Time, Acc_X/Y/Z, Gyro_X/Y/Z
        NNN_TaskName_RightWrist.txt
    patients/
      patient_NNN.json             # demographics, diagnosis
    questionnaire/
      questionnaire_response_NNN.json
    preprocessed/
      ...

Sampling rate: 100 Hz
Channels: Time, Accelerometer_X/Y/Z, Gyroscope_X/Y/Z
Tasks: Relaxed, RelaxedTask, StretchHold, LiftHold, HoldWeight,
       PointFinger, DrinkGlas, CrossArms, TouchIndex, TouchNose, Entrainment
"""
import json
import numpy as np
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PADSRecord:
    """One task recording from one wrist of one subject."""
    subject_id: int
    task_name: str
    wrist: str  # "LeftWrist" or "RightWrist"
    accel_xyz: np.ndarray  # (N, 3)
    gyro_xyz: np.ndarray   # (N, 3)
    time: np.ndarray       # (N,)
    fs: float
    diagnosis: Optional[str]  # "PD", "DD", "HC"
    metadata: dict


@dataclass(frozen=True)
class PADSSubject:
    """All data for one subject."""
    subject_id: int
    diagnosis: Optional[str]
    age: Optional[int]
    sex: Optional[str]
    records: tuple[PADSRecord, ...]  # immutable tuple


def load_patient_info(patients_dir: Path) -> dict[int, dict]:
    """Load patient demographics and diagnosis from JSON files."""
    info = {}
    for f in sorted(patients_dir.glob("patient_*.json")):
        try:
            with open(f) as fh:
                data = json.load(fh)
            sid = int(f.stem.split("_")[1])
            info[sid] = data
        except (json.JSONDecodeError, ValueError):
            continue
    return info


def load_timeseries(filepath: Path) -> Optional[tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Load a single timeseries file.

    Returns:
        (time, accel_xyz, gyro_xyz) or None if file cannot be loaded
    """
    try:
        data = np.loadtxt(str(filepath))
    except Exception:
        return None

    if data.ndim != 2 or data.shape[1] < 7:
        return None

    time = data[:, 0]
    accel = data[:, 1:4]  # Acc X, Y, Z
    gyro = data[:, 4:7]   # Gyro X, Y, Z

    return time, accel, gyro


def load_pads_dataset(base_dir: str) -> list[PADSSubject]:
    """Load the full PADS dataset.

    Args:
        base_dir: Path to the dataset root (containing movement/, patients/, etc.)

    Returns:
        List of PADSSubject objects
    """
    base = Path(base_dir)
    movement_dir = base / "movement"
    timeseries_dir = movement_dir / "timeseries"
    patients_dir = base / "patients"

    # Load patient info
    patient_info = load_patient_info(patients_dir)
    print(f"Loaded info for {len(patient_info)} patients")

    # Load observation metadata
    obs_files = sorted(movement_dir.glob("observation_*.json"))
    print(f"Found {len(obs_files)} observation files")

    subjects = {}

    for obs_file in obs_files:
        try:
            with open(obs_file) as f:
                obs = json.load(f)
        except json.JSONDecodeError:
            continue

        sid = int(obs.get("subject_id", obs_file.stem.split("_")[1]))
        fs = float(obs.get("sampling_rate", 100))

        # Get diagnosis from patient info
        pat = patient_info.get(sid, {})
        diagnosis = pat.get("diagnosis", pat.get("group", None))

        records = []
        for session in obs.get("session", []):
            task_name = session.get("record_name", "Unknown")

            for rec in session.get("records", []):
                wrist = rec.get("device_location", "Unknown")
                filename = rec.get("file_name", "")

                filepath = movement_dir / filename
                if not filepath.exists():
                    continue

                result = load_timeseries(filepath)
                if result is None:
                    continue

                time, accel, gyro = result

                records.append(PADSRecord(
                    subject_id=sid,
                    task_name=task_name,
                    wrist=wrist,
                    accel_xyz=accel,
                    gyro_xyz=gyro,
                    time=time,
                    fs=fs,
                    diagnosis=diagnosis,
                    metadata={
                        "file": str(filepath),
                        "channels": rec.get("channels", []),
                    },
                ))

        if records:
            subjects[sid] = PADSSubject(
                subject_id=sid,
                diagnosis=diagnosis,
                age=pat.get("age"),
                sex=pat.get("sex"),
                records=tuple(records),
            )

    result = list(subjects.values())
    print(f"Loaded {len(result)} subjects with {sum(len(s.records) for s in result)} total recordings")
    return result


def pads_to_arrays(
    subjects: list[PADSSubject],
    task_filter: Optional[list[str]] = None,
    wrist: str = "LeftWrist",
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Convert PADS subjects to numpy arrays for training.

    Args:
        subjects: List of PADSSubject
        task_filter: Only include these tasks (None = all)
        wrist: Which wrist to use

    Returns:
        imu: (N, T, 6) array of IMU windows
        labels: (N,) diagnosis labels (0=HC, 1=PD, 2=DD)
        subject_ids: (N,) subject IDs
        task_names: (N,) task names
    """
    label_map = {"HC": 0, "PD": 1, "DD": 2}

    imu_list = []
    labels_list = []
    sids_list = []
    tasks_list = []

    for subj in subjects:
        if subj.diagnosis not in label_map:
            continue

        label = label_map[subj.diagnosis]

        for rec in subj.records:
            if rec.wrist != wrist:
                continue
            if task_filter and rec.task_name not in task_filter:
                continue

            # Combine accel + gyro
            imu = np.concatenate([rec.accel_xyz, rec.gyro_xyz], axis=1)  # (T, 6)
            imu_list.append(imu)
            labels_list.append(label)
            sids_list.append(subj.subject_id)
            tasks_list.append(rec.task_name)

    return imu_list, np.array(labels_list), np.array(sids_list), np.array(tasks_list)


if __name__ == "__main__":
    import sys
    base = sys.argv[1] if len(sys.argv) > 1 else "/root/pd-imu/data/raw/pads/physionet.org/files/parkinsons-disease-smartwatch/1.0.0"
    subjects = load_pads_dataset(base)

    # Summary
    diag_counts = {}
    for s in subjects:
        d = s.diagnosis or "Unknown"
        diag_counts[d] = diag_counts.get(d, 0) + 1

    print("\nDiagnosis distribution:")
    for d, c in sorted(diag_counts.items()):
        print(f"  {d}: {c}")

    print(f"\nTotal subjects: {len(subjects)}")
    print(f"Total recordings: {sum(len(s.records) for s in subjects)}")
