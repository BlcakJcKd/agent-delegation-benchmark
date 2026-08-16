"""Safe, consultation-first wrappers for delegated CLI agents.

This package is intentionally separate from :mod:`benchmark`: benchmark run
artifacts are immutable evidence, while this package is operational tooling.
"""

from .core import (
    DELEGATES,
    DELEGATION_CALLER_ENV,
    DELEGATION_DEPTH_ENV,
    DelegateSpec,
    build_argv,
    run_consultation,
)

__all__ = [
    "DELEGATES",
    "DELEGATION_CALLER_ENV",
    "DELEGATION_DEPTH_ENV",
    "DelegateSpec",
    "build_argv",
    "run_consultation",
]
