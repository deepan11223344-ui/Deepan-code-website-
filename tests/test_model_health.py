"""Tests for model health module (no live network — HTTP layer mocked)."""

import pytest
from deepans_code import model_health
from deepans_code.model_health import (
    check_model_health, get_model_context_window,
    get_all_health_status
)


@pytest.fixture(autouse=True)
def clear_health_cache():
    model_health._health_cache.clear()
    yield
    model_health._health_cache.clear()


class TestModelHealth:
    def test_context_window_known_model(self):
        window = get_model_context_window("openrouter/free")
        assert window == 200000  # authoritative: deepans_code.models registry

    def test_context_window_claude(self):
        window = get_model_context_window("claude-3-opus")
        assert window == 200000

    def test_context_window_gpt4(self):
        window = get_model_context_window("gpt-4")
        assert window == 128000

    def test_context_window_gpt5(self):
        window = get_model_context_window("gpt-5")
        assert window == 400000

    def test_context_window_gemini(self):
        window = get_model_context_window("gemini-2.5-pro")
        assert window == 1048576  # authoritative: deepans_code.models registry

    def test_context_window_unknown(self):
        window = get_model_context_window("some-random-model")
        assert window == 128000

    def test_health_check_mocked(self, monkeypatch):
        monkeypatch.setattr(
            model_health, "_check_openrouter",
            lambda model_id, api_key: {"status": "down", "error": "mocked"})
        result = check_model_health("nonexistent-model", "fake-key")
        assert result["status"] == "down"
        assert "last_check" in result

    def test_health_cache(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            model_health, "_check_openrouter",
            lambda model_id, api_key: calls.append(1) or {"status": "down"})
        # First call should check
        result1 = check_model_health("nonexistent-model", "fake-key")
        assert "status" in result1
        # Second call should use cache (no extra backend call)
        result2 = check_model_health("nonexistent-model", "fake-key")
        assert result1.get("last_check") == result2.get("last_check")
        assert len(calls) == 1
