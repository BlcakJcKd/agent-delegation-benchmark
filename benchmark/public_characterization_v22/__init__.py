"""Public Characterization V2.2: structurally calibrated synthetic tasks."""

SUITE_NAME = "public-characterization-v2.2"
SUITE_VERSION = "2.2"
EVALUATION_CLASS = "public_characterization"
FAMILIES = ("P1_stateful_inventory", "P3_scientific_pipeline")
CALIBRATION_SEED = 20262201
EVALUATION_SEEDS = {"P1_stateful_inventory": 20262211, "P3_scientific_pipeline": 20262213}
CALIBRATION_CONFIG = ("gemini-3.7-flash-medium", "medium")
COMPARISON_CONFIGURATIONS = (
    ("gemini-3.7-flash-low", "low"),
    ("gemini-3.7-flash-medium", "medium"),
    ("gemini-3.8-flash-low", "low"),
)
CHECK_COUNT = 8
BASELINE_MAXIMUM = 75.0
BASELINE_TARGET = (12.5, 37.5)
ATTEMPT_TIMEOUT_SECONDS = 900
PHASE_CALIBRATION = "task_calibration"
PHASE_COMPARATIVE = "comparative_characterization"
IGNORED_GENERATED_DIRS = ("__pycache__", ".pytest_cache")
IGNORED_GENERATED_SUFFIXES = (".pyc",)

