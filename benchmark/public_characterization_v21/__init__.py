"""Public Characterization V2.1: harder, public, baseline-aware tasks."""

SUITE_NAME = "public-characterization-v2.1"
SUITE_VERSION = "2.1"
EVALUATION_CLASS = "public_characterization"
FAMILIES = ("P1_multi_file_state", "P2_config_session", "P3_scientific_pipeline", "P4_compatibility")
PILOT_CONFIGURATIONS = (
    ("gemini-3.7-flash-low", "low"),
    ("gemini-3.7-flash-medium", "medium"),
    ("gemini-3.8-flash-low", "low"),
)
PHASE_A_FAMILIES = ("P1_multi_file_state", "P3_scientific_pipeline")
PHASE_B_FAMILIES = ("P2_config_session", "P4_compatibility")
IGNORED_GENERATED_SUFFIXES = (".pyc",)
IGNORED_GENERATED_DIRS = ("__pycache__", ".pytest_cache")
BASELINE_MAXIMUM = 75.0
BASELINE_TARGET = (12.5, 37.5)
CHECK_COUNT = 8
