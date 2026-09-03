"""Small, offline plotting helpers for ledger-derived reports.

Plot files are derived artifacts. The ledger and report rows remain the source
of truth; an empty or invalid observation set is reported as a skipped plot so
callers do not mistake an empty matplotlib canvas for data.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterable


def _is_valid(row: dict[str, Any]) -> bool:
    if row.get("valid") is False or row.get("status") in {"invalid", "invalidated", "failed"}:
        return False
    return True


def plot_rows(
    rows: Iterable[dict[str, Any]],
    path: Path,
    *,
    x_key: str,
    y_key: str,
    xlabel: str,
    ylabel: str,
    title: str | None = None,
) -> dict[str, Any]:
    """Plot numeric/categorical ledger rows or return structured skip metadata."""
    observations = [
        row for row in rows
        if _is_valid(row) and row.get(x_key) is not None and row.get(y_key) is not None
        and _finite(row.get(y_key))
    ]
    if not observations:
        return {"status": "skipped", "reason": "no_valid_observations", "path": None}

    import matplotlib.pyplot as plt

    x_values = [row[x_key] for row in observations]
    y_values = [row[y_key] for row in observations]
    numeric_x = all(_finite(value) for value in x_values)
    plotted_x: list[Any] = x_values
    if not numeric_x:
        plotted_x = list(range(len(x_values)))

    path.parent.mkdir(parents=True, exist_ok=True)
    plt.figure(figsize=(9, 5))
    plt.plot(plotted_x, y_values, "o-")
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    if title:
        plt.title(title)
    if not numeric_x:
        plt.xticks(plotted_x, [str(value) for value in x_values], rotation=35, ha="right")
    plt.tight_layout()
    plt.savefig(path)
    plt.close()
    return {"status": "created", "reason": None, "path": str(path), "observations": len(observations)}


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False
