"""First frozen cross-provider characterization using the R1.1 portfolio."""

SUITE_NAME = "cross-provider-characterization-r1"
SUITE_VERSION = "1.0"
EVALUATION_CLASS = "public_characterization"
TIMEOUT_SECONDS = 420
RETRIES = 0
R1_1_SUITE = "gemini-3.8-reasoning-r1.1"
R1_1_SHA = "78298561c5542bec5a2b87aff34179871522e7ac"
FAMILIES = ("R1_maintenance", "R2_api_compat", "R3_scientific_pipeline", "R4_config_state")
SEEDS = {family: 20261004 + index for index, family in enumerate(FAMILIES)}
CONFIGS = (
    {"name": "deepseek-flash", "provider": "deepseek", "model": "deepseek-v4-flash", "reasoning": "high", "transport": "codex", "billing": "payg", "executable": "codex-deepseek"},
    {"name": "minimax-m3", "provider": "minimax", "model": "MiniMax-M3", "reasoning": "high", "transport": "codex", "billing": "payg", "executable": "codex-minimax"},
)
# Eight new cells, balanced across the two providers and four frozen tasks.
RUN_ORDER = ((0, 0), (1, 1), (0, 2), (1, 3), (1, 0), (0, 1), (1, 2), (0, 3))
SUITE_SOURCE_PATHS = (
    "benchmark/cross_provider_characterization_r1/__init__.py",
    "benchmark/cross_provider_characterization_r1/runner.py",
    "benchmark/gemini_reasoning_r1_1/__init__.py",
    "benchmark/gemini_reasoning_r1_1/generate.py",
    "benchmark/gemini_reasoning_r1_1/evaluate.py",
    "benchmark/adapters.py",
    "benchmark/edit_scope.py",
    "benchmark/provenance.py",
    "benchmark/v2/telemetry.py",
    "ekalavya/ledger.py",
    "ekalavya/harness_registry.py",
)
