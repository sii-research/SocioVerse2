"""Make the repo root importable so tests can `import studies.chicago_schelling...`.

Also gates the `llm` marker: tests that need a live LLM endpoint are skipped unless
SV_RUN_LLM_TESTS=1, so a plain `pytest` never needs a key and never spends tokens.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))


def pytest_collection_modifyitems(config, items):
    if os.environ.get("SV_RUN_LLM_TESTS") == "1":
        return
    skip_llm = pytest.mark.skip(reason="live-LLM test; set SV_RUN_LLM_TESTS=1 to run")
    for item in items:
        if "llm" in item.keywords:
            item.add_marker(skip_llm)
