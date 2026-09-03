"""Validated, baseline-aware public characterization V2."""

SUITE_NAME = "public-characterization-v2"
SUITE_VERSION = "2.0"
EVALUATION_CLASS = "public_characterization"
FAMILIES = ("P1_multi_file_debug", "P2_config_state", "P3_data_pipeline", "P4_compat_refactor")
PILOT_CONFIGURATIONS = (
    ("gemini-3.7-flash-low", "low"),
    ("gemini-3.7-flash-medium", "medium"),
    ("gemini-3.8-flash-low", "low"),
)
IGNORED_GENERATED_SUFFIXES = (".pyc",)
IGNORED_GENERATED_DIRS = ("__pycache__", ".pytest_cache")
BASELINE_MAXIMUM = 75.0
BASELINE_TARGET = (12.5, 37.5)
