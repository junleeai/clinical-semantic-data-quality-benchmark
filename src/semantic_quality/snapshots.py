"""Deterministic serialization and safe publication for local dataset snapshots."""

import hashlib
import json
import tempfile
from pathlib import Path


def json_bytes(value, *, pretty=False) -> bytes:
    text = json.dumps(
        value, sort_keys=True, allow_nan=False,
        indent=2 if pretty else None, separators=None if pretty else (",", ":"),
    )
    return (text + "\n").encode("utf-8")


def jsonl_bytes(rows) -> bytes:
    return b"".join(json_bytes(row) for row in rows)


def fingerprint(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def publish_snapshot(destination: Path, files: dict[str, bytes]) -> None:
    """Publish a whole directory at once. Treat identical replays as no-ops."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".staging-", dir=destination.parent) as directory:
        staging = Path(directory) / "snapshot"
        for name, data in files.items():
            path = staging / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        try:
            staging.rename(destination)
        except OSError:
            if not destination.is_dir():
                raise
            existing = {str(path.relative_to(destination)) for path in destination.rglob("*") if path.is_file()}
            if existing != files.keys() or any(
                (destination / name).read_bytes() != data for name, data in files.items()
            ):
                raise ValueError(f"Snapshot already exists with different contents: {destination}") from None
