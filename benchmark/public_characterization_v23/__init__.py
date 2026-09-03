"""Public Characterization V2.3: feature-integration calibration."""
from __future__ import annotations

SUITE_NAME = "public-characterization-v2.3"
SUITE_VERSION = "2.3"
EVALUATION_CLASS = "public_characterization"
FAMILIES = ("P1_snapshot_inventory",)
CALIBRATION_SEED = 20262301
EVALUATION_SEED = 20262311
CALIBRATION_CONFIG = ("gemini-3.7-flash-medium", "medium")
COMPARISON_CONFIGURATIONS = (
    ("gemini-3.7-flash-low", "low"),
    ("gemini-3.7-flash-medium", "medium"),
    ("gemini-3.8-flash-low", "low"),
)
CHECK_COUNT = 8
BASELINE_MAXIMUM = 75.0
NEW_FEATURE_TARGET = (0.0, 37.5)
ATTEMPT_TIMEOUT_SECONDS = 420
PHASE_CALIBRATION = "task_calibration"
PHASE_COMPARATIVE = "comparative_characterization"
IGNORED_GENERATED_DIRS = ("__pycache__", ".pytest_cache")
IGNORED_GENERATED_SUFFIXES = (".pyc",)
