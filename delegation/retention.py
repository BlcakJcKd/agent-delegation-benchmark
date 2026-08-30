"""Private, atomic retention of external-delegate response evidence.

Delegate responses can contain private source material, so this module keeps
them in the per-run state directory rather than in a repository workspace or
public log.  ``stdout.txt`` remains the response channel for compatibility,
but it is now written durably before a successful run is finalized.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


RESPONSE_FILENAME = "stdout.txt"


class ResponseRetentionError(OSError):
    """A response could not be safely read from or written to run state."""


def _ensure_private_record_dir(record_dir: Path) -> None:
    """Ensure the run directory is a private, non-symlink directory."""
    if record_dir.is_symlink() or not record_dir.is_dir():
        raise ResponseRetentionError("delegate response record directory is unavailable")
    try:
        os.chmod(record_dir, 0o700)
    except OSError as exc:
        raise ResponseRetentionError("delegate response record directory is not private") from exc


def atomic_write_text(path: Path, text: str) -> None:
    """Write UTF-8 text with mode 0600 and atomically replace ``path``."""
    if not isinstance(text, str):
        raise TypeError("delegate capture must be text")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = -1
    temporary: Path | None = None
    try:
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent, text=True,
        )
        temporary = Path(temporary_name)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            fd = -1
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    except OSError as exc:
        raise ResponseRetentionError("delegate response could not be retained") from exc
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def persist_text(record_dir: Path, filename: str, text: str) -> None:
    """Atomically retain one private per-run text capture."""
    if Path(filename).name != filename or filename in {"", ".", ".."}:
        raise ValueError("record filename must be a simple relative name")
    _ensure_private_record_dir(record_dir)
    atomic_write_text(record_dir / filename, text)


def persist_response(record_dir: Path, text: str) -> dict[str, Any]:
    """Retain a delegate response and return safe metadata about the file.

    Whitespace-only captures are retained for compatibility with partial/error
    diagnostics, but are not considered a recorded textual response.
    """
    persist_text(record_dir, RESPONSE_FILENAME, text)
    encoded = text.encode("utf-8")
    return {
        "response_recorded": bool(text.strip()),
        "response_file": RESPONSE_FILENAME,
        "response_length_bytes": len(encoded),
        "response_sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _safe_response_filename(value: Any) -> str:
    if not isinstance(value, str) or Path(value).name != value or value in {"", ".", ".."}:
        raise ResponseRetentionError("delegate response locator is invalid")
    return value


def read_response(record_dir: Path) -> str:
    """Read the retained response, rejecting an ambiguous success record.

    Older records did not have response metadata, so they continue to use the
    established ``stdout.txt`` fallback.  New text-returned records must prove
    that their response was retained before the CLI treats them as usable.
    """
    metadata_path = record_dir / "execution.json"
    metadata: dict[str, Any] | None = None
    if metadata_path.is_file():
        try:
            parsed = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ResponseRetentionError("delegate response metadata is unreadable") from exc
        if not isinstance(parsed, dict):
            raise ResponseRetentionError("delegate response metadata is invalid")
        metadata = parsed

    if metadata is not None:
        status = metadata.get("response_status")
        recorded = metadata.get("response_recorded")
        if status == "text-returned" and recorded is not True:
            raise ResponseRetentionError(
                "delegate metadata reports text-returned without a retained response"
            )
        filename = metadata.get("response_file")
        if filename is None:
            filename = metadata.get("stdout_file", RESPONSE_FILENAME)
        filename = _safe_response_filename(filename)
    else:
        filename = RESPONSE_FILENAME

    response_path = record_dir / filename
    if not response_path.is_file() or response_path.is_symlink():
        if metadata is not None and (
            metadata.get("response_status") == "text-returned"
            or metadata.get("response_recorded") is True
        ):
            raise ResponseRetentionError("delegate response file is missing")
        return ""
    try:
        return response_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ResponseRetentionError("delegate response file is unreadable") from exc
