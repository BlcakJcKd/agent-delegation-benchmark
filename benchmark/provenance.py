"""Git provenance checks for reproducible benchmark implementations."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any, Iterable


class ProvenanceError(ValueError):
    """Raised when a claimed Git identity cannot reproduce its source."""


def _git(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=repo, text=True, capture_output=True, check=False,
        )
    except OSError as exc:
        raise ProvenanceError(f"Git unavailable: {exc}") from exc
    if result.returncode != 0:
        raise ProvenanceError((result.stderr or "git command failed").strip())
    return result.stdout.strip()


def _blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode()
    return hashlib.sha1(header + data).hexdigest()


def validate_git_identity(
    repo: Path,
    source_paths: Iterable[str],
    *,
    git_sha: str | None = None,
) -> dict[str, Any]:
    """Return a reproducible source identity, rejecting dirty/mismatched trees."""
    root = Path(repo).resolve()
    paths = tuple(sorted(dict.fromkeys(source_paths)))
    if not paths:
        raise ProvenanceError("suite source path allowlist is empty")
    sha = git_sha or _git(root, "rev-parse", "HEAD")
    if len(sha) < 7:
        raise ProvenanceError(f"invalid Git identity: {sha!r}")
    source_hashes: dict[str, str] = {}
    for relative in paths:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise ProvenanceError(f"suite source is not a regular file: {relative}")
        tracked = _git(root, "ls-files", "--error-unmatch", "--", relative)
        if tracked != relative:
            raise ProvenanceError(f"suite source is not tracked: {relative}")
        try:
            committed_blob = _git(root, "rev-parse", f"{sha}:{relative}")
        except ProvenanceError as exc:
            raise ProvenanceError(f"{sha} does not contain suite source {relative}") from exc
        actual = path.read_bytes()
        if _blob_sha(actual) != committed_blob:
            raise ProvenanceError(f"working-tree source differs from {sha}: {relative}")
        source_hashes[relative] = hashlib.sha256(actual).hexdigest()
    return {"git_sha": _git(root, "rev-parse", sha), "source_paths": list(paths), "source_sha256": source_hashes}
