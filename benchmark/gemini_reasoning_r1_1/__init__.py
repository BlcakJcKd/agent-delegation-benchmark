"""Fresh matched public Gemini 3.8 reasoning-level characterization portfolio."""

SUITE_NAME = "gemini-3.8-reasoning-r1.1"
SUITE_VERSION = "1.1"
EVALUATION_CLASS = "public_characterization"
FAMILIES = ("R1_maintenance", "R2_api_compat", "R3_scientific_pipeline", "R4_config_state")
SEEDS = {family: 20261004 + index for index, family in enumerate(FAMILIES)}
TIMEOUT_SECONDS = 420

SUITE_SOURCE_PATHS = (
    "benchmark/gemini_reasoning_r1_1/__init__.py",
    "benchmark/gemini_reasoning_r1_1/generate.py",
    "benchmark/gemini_reasoning_r1_1/evaluate.py",
    "benchmark/gemini_reasoning_r1_1/runner.py",
    "benchmark/v2/plotting.py",
    "benchmark/v2/telemetry.py",
    "benchmark/adapters.py",
    "benchmark/provenance.py",
    "ekalavya/ledger.py",
    "ekalavya/harness_registry.py",
    "benchmark/edit_scope.py",
)
