"""Public Characterization V2.4: repository-scale feature integration."""

SUITE_NAME = "public-characterization-v2.4"
SUITE_VERSION = "2.4"
EVALUATION_CLASS = "public_characterization"
FAMILY = "P1_named_report_bookmarks"
CALIBRATION_SEED = 20262401
EVALUATION_SEED = 20262411  # reserved; no comparative run in this task
CALIBRATION_CONFIG = ("gemini-3.7-flash-medium", "medium")
COMPARISON_CONFIGURATIONS = (
    ("gemini-3.7-flash-low", "low"),
    ("gemini-3.7-flash-medium", "medium"),
    ("gemini-3.8-flash-low", "low"),
)
FAMILIES = (FAMILY,)
CHECK_COUNT = 8
BASELINE_MAXIMUM = 75.0
NEW_FEATURE_TARGET = (0.0, 37.5)
ATTEMPT_TIMEOUT_SECONDS = 480
PHASE_CALIBRATION = "task_calibration"
PHASE_COMPARATIVE = "comparative_characterization"
IGNORED_GENERATED_DIRS = ("__pycache__", ".pytest_cache")
IGNORED_GENERATED_SUFFIXES = (".pyc",)

# Controller-side design metadata.  This is not supplied to a candidate and
# contains no repair recipe.
FEATURE_CLUSTERS = (
    {"id": "query_semantics", "domains": ["normalization", "compound filters"]},
    {"id": "owner_scoped_state", "domains": ["independent owners", "lifecycle"]},
    {"id": "service_orchestration", "domains": ["mutation evolution", "API propagation"]},
    {"id": "portable_persistence", "domains": ["round-trip", "validation"]},
    {"id": "report_integration", "domains": ["metadata", "summary composition"]},
)

FEATURE_VOCABULARY = (
    "bookmark", "saved search", "saved query", "named report", "report bookmark",
    "create_bookmark", "run_bookmark", "export_bookmark", "import_bookmark",
)
