"""Public, objective, non-adversarially-isolated characterization suite."""

SUITE_NAME = "public-characterization-v1"
SUITE_VERSION = "1.0"
EVALUATION_CLASS = "public_characterization"
FAMILIES = ("P1_multi_file_debug", "P2_config_state", "P3_data_pipeline", "P4_compat_refactor")
SUITE_SOURCE_PATHS = (
    "benchmark/public_characterization/__init__.py",
    "benchmark/public_characterization/generate.py",
    "benchmark/public_characterization/evaluate.py",
    "benchmark/public_characterization/runner.py",
    "benchmark/v2/telemetry.py",
    "benchmark/adapters.py",
    "ekalavya/ledger.py",
    "ekalavya/harness_registry.py",
)
