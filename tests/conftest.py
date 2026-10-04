import pytest


@pytest.fixture
def home(tmp_path, monkeypatch):
    """An isolated ~/.recall and memory file for CLI, hook and MCP tests."""
    rh = tmp_path / "recall-home"
    monkeypatch.setenv("RECALL_HOME", str(rh))
    monkeypatch.setenv("RECALL_DB", str(rh / "memory.json"))
    for var in ("RECALL_CONFIRM", "RECALL_SELF_CHECK", "RECALL_CAPTURE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)
    return rh
