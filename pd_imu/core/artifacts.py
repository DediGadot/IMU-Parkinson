"""Filesystem-backed artifact observation contracts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


HEX_CHARS = set("0123456789abcdefABCDEF")


@dataclass(frozen=True)
class ArtifactRecord:
    """Observed state for one artifact path."""

    path: str
    exists: bool
    size_bytes: int | None = None
    sha256: str | None = None

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.path, str):
            errors.append("artifact path must be a string")
        elif not self.path:
            errors.append("artifact path is required")
        if not isinstance(self.exists, bool):
            errors.append("artifact exists must be a boolean")
        if self.size_bytes is not None and (not isinstance(self.size_bytes, int) or isinstance(self.size_bytes, bool)):
            errors.append("artifact size_bytes must be an integer when set")
        elif self.size_bytes is not None and self.size_bytes < 0:
            errors.append("artifact size_bytes cannot be negative")
        if self.exists is True and self.size_bytes is None:
            errors.append("existing artifact must include size_bytes")
        if self.exists is False and self.size_bytes is not None:
            errors.append("missing artifact must not include size_bytes")
        if self.sha256 is not None and (not isinstance(self.sha256, str) or not _is_sha256_hex(self.sha256)):
            errors.append("artifact sha256 must be 64 hex characters when set")
        if self.exists is False and self.sha256 is not None:
            errors.append("missing artifact must not include sha256")
        return errors


@dataclass(frozen=True)
class ArtifactLedger:
    """A small immutable ledger of artifact paths observed on disk."""

    records: tuple[ArtifactRecord, ...]
    input_errors: tuple[str, ...] = ()

    @classmethod
    def from_paths(
        cls,
        paths: tuple[str, ...] | list[str],
        *,
        root: str | Path = ".",
        hash_existing: bool = False,
    ) -> "ArtifactLedger":
        input_errors: list[str] = []
        if not isinstance(paths, tuple | list):
            return cls(records=(), input_errors=("paths must be a tuple or list",))
        if not isinstance(root, str | Path):
            return cls(records=(), input_errors=("root must be a string or Path",))
        if not isinstance(hash_existing, bool):
            input_errors.append("hash_existing must be a boolean")
            hash_existing = False
        root_path = Path(root)
        records: list[ArtifactRecord] = []
        for raw_path in paths:
            if not isinstance(raw_path, str):
                records.append(ArtifactRecord(path=raw_path, exists=False))
                continue
            if not raw_path:
                records.append(ArtifactRecord(path=raw_path, exists=False))
                continue
            try:
                artifact_path = Path(raw_path)
                resolved = artifact_path if artifact_path.is_absolute() else root_path / artifact_path
                exists = resolved.exists()
            except (OSError, ValueError) as exc:
                input_errors.append(f"artifact path could not be observed: {raw_path}: {exc}")
                records.append(ArtifactRecord(path=raw_path, exists=False))
                continue
            if not exists:
                records.append(ArtifactRecord(path=raw_path, exists=False))
                continue
            try:
                stat = resolved.stat()
            except OSError as exc:
                input_errors.append(f"artifact path could not be statted: {raw_path}: {exc}")
                records.append(ArtifactRecord(path=raw_path, exists=False))
                continue
            artifact_sha256: str | None = None
            if hash_existing:
                try:
                    artifact_sha256 = _sha256_file(resolved)
                except OSError as exc:
                    input_errors.append(f"artifact path could not be hashed: {raw_path}: {exc}")
            records.append(
                ArtifactRecord(
                    path=raw_path,
                    exists=True,
                    size_bytes=stat.st_size,
                    sha256=artifact_sha256,
                )
            )
        return cls(records=tuple(records), input_errors=tuple(input_errors))

    def observed_paths(self) -> tuple[str, ...]:
        return tuple(record.path for record in _record_values(self.records) if record.exists is True and isinstance(record.path, str))

    def missing_paths(self, paths: tuple[str, ...] | list[str]) -> tuple[str, ...]:
        observed = set(self.observed_paths())
        return tuple(path for path in dict.fromkeys(_string_values(paths)) if path not in observed)

    def validation_errors(self) -> list[str]:
        errors: list[str] = list(self.input_errors) if isinstance(self.input_errors, tuple | list) else [
            "input_errors must be a tuple or list"
        ]
        if not isinstance(self.records, tuple | list):
            return [*errors, "records must be a tuple or list"]
        for error in _string_collection_errors(self.input_errors, field_name="input_errors"):
            errors.append(error)
        for record in self.records:
            if not isinstance(record, ArtifactRecord):
                errors.append("records entries must be ArtifactRecord")
        records = _record_values(self.records)
        for record in records:
            errors.extend(record.validation_errors())
        paths = [record.path for record in records if isinstance(record.path, str)]
        for path in paths:
            if not path:
                errors.append("artifact path is required")
        for path in sorted({path for path in paths if path and paths.count(path) > 1}):
            errors.append(f"duplicate artifact path: {path}")
        return errors

    def record_for(self, path: str) -> ArtifactRecord | None:
        for record in _record_values(self.records):
            if record.path == path:
                return record
        return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _record_values(values: Any) -> tuple[ArtifactRecord, ...]:
    if not isinstance(values, tuple | list):
        return ()
    return tuple(record for record in values if isinstance(record, ArtifactRecord))


def _string_values(values: Any) -> tuple[str, ...]:
    if not isinstance(values, tuple | list):
        return ()
    return tuple(value for value in values if isinstance(value, str) and value)


def _string_collection_errors(values: Any, *, field_name: str) -> list[str]:
    if not isinstance(values, tuple | list):
        return []
    if any(not isinstance(value, str) or not value for value in values):
        return [f"{field_name} entries must be non-empty strings"]
    return []


def _is_sha256_hex(value: str) -> bool:
    return len(value) == 64 and all(char in HEX_CHARS for char in value)
