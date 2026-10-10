import pytest

from aijury.config import Budget, Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(
        provider="mock",
        budget=Budget(max_rounds=3, max_jurors=3, max_tokens=500_000, max_llm_calls=200),
        trace_dir=str(tmp_path / "traces"),
        failure_dir=str(tmp_path / "failures"),
        gateways_path=str(tmp_path / "gateways.json"),
    )
