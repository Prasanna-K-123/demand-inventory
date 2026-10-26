from pathlib import Path
import pytest
BASE=Path(__file__).resolve().parents[1]
def pytest_configure(config):
    config.addinivalue_line("markers", "requires_model: full-study checks requiring the locally regenerated fitted artifact")
def pytest_collection_modifyitems(config,items):
    if not (BASE/"artifacts/models.pkl").exists():
        skip=pytest.mark.skip(reason="Fitted artifacts are excluded from public distribution; run scripts/research.py for full-study checks")
        for item in items:
            if "requires_model" in item.keywords:item.add_marker(skip)
