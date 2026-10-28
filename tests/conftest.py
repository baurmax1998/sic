"""Gemeinsame Fixtures für optionale lokale Modelltests."""
import os
from pathlib import Path
import sys
import time

import pytest


@pytest.fixture(scope="session")
def backend():
    """Lädt das Modell aus dem benachbarten lokal_llm-Projekt nur bei Bedarf."""
    sibling = Path(__file__).resolve().parents[2] / "lokal_llm"
    if not sibling.is_dir():
        pytest.skip("Das benachbarte lokal_llm-Projekt ist nicht verfügbar")
    sys.path.insert(0, str(sibling))
    from src.llm import DEFAULT_MODEL, MLXModelBackend

    started = time.perf_counter()
    instance = MLXModelBackend(os.getenv("TEST_MODEL_ID", DEFAULT_MODEL))
    print(f"\nModell laden: {time.perf_counter() - started:.3f} s")
    return instance
