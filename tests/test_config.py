"""Tests for config module (isolated to tmp_path — never touches ~/.deepans-code)."""

import copy
import json
import pytest
from pathlib import Path
from pydantic import ValidationError
from deepans_code import config as config_mod
from deepans_code.config import (
    ConfigManager, DEFAULT_CONFIG, DeepanCodeConfig, load_config,
)


@pytest.fixture
def temp_config(tmp_path, monkeypatch):
    """Create a temporary config manager fully isolated in tmp_path."""
    fake_dir = tmp_path / ".deepans-code"
    fake_dir.mkdir()
    fake_file = fake_dir / "config.json"

    test_config = copy.deepcopy(DEFAULT_CONFIG)
    test_config["model"] = "openrouter/free"
    test_config["provider"] = "openrouter"
    test_config["connectors"] = {"openrouter": "", "opencode": ""}

    with open(fake_file, "w", encoding="utf-8") as f:
        json.dump(test_config, f)

    monkeypatch.setattr(config_mod, "CONFIG_DIR", fake_dir)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", fake_file)

    mgr = ConfigManager()
    yield mgr
    # tmp_path is torn down automatically; real user config never touched.


class TestConfigManager:
    def test_get_default(self, temp_config):
        assert temp_config.get("model") == "openrouter/free"
        assert temp_config.get("nonexistent", "default") == "default"

    def test_set_and_get(self, temp_config):
        temp_config.set("mode", "chat")
        assert temp_config.get("mode") == "chat"

    def test_save_and_reload(self, temp_config):
        temp_config.set("mode", "test")
        temp_config.save()
        temp_config.config = temp_config.load()
        assert temp_config.get("mode") == "test"

    def test_set_connector(self, temp_config):
        temp_config.set_connector("openrouter", "sk-test12345")
        key = temp_config.get_api_key("openrouter")
        assert key == "sk-test12345"

    def test_set_connector_strips_quotes(self, temp_config):
        temp_config.set_connector("openrouter", '"sk-quoted-12345"')
        key = temp_config.get_api_key("openrouter")
        assert key == "sk-quoted-12345"

    def test_set_connector_strips_bearer(self, temp_config):
        temp_config.set_connector("openrouter", "Bearer sk-bearer-12345")
        key = temp_config.get_api_key("openrouter")
        assert key == "sk-bearer-12345"

    def test_set_connector_rejects_garbage(self, temp_config):
        with pytest.raises(ValueError):
            temp_config.set_connector("openrouter", "short")

    def test_token_tracking(self, temp_config):
        temp_config.token_usage.track_usage(100)
        temp_config.token_usage.track_usage(200)
        usage = temp_config.token_usage.get_usage()
        assert usage["tokens_used"] == 300
        assert usage["daily_used"] == 300
        assert usage["monthly_used"] == 300

    def test_session_summary(self, temp_config):
        temp_config.token_usage.track_usage(500)
        summary = temp_config.token_usage.check_limit()
        assert summary["daily_used"] == 500
        assert summary["monthly_used"] == 500
        assert summary["daily_percentage"] >= 0


class TestStrictSchema:
    def test_repo_config_validates(self):
        repo_config = Path(__file__).parent.parent / "Deepancode.json"
        cfg = load_config(str(repo_config))
        assert cfg.default_provider == "openrouter"
        assert cfg.providers.opencode_zen.default_model == "big-pickle"
        assert cfg.models["coding"].model_id == "cohere/north-mini-code:free"

    def test_typo_is_rejected(self):
        with pytest.raises(ValidationError):
            DeepanCodeConfig.model_validate({
                "defaultProvider": "openrouter",
                "providers": {},
                "colur": "blue",  # typo must fail loudly, not be ignored
            })

    def test_unknown_provider_field_rejected(self):
        with pytest.raises(ValidationError):
            DeepanCodeConfig.model_validate({
                "defaultProvider": "openrouter",
                "providers": {"openrouter": {"baseURL": "https://x", "bogus": 1}},
            })

    def test_snake_case_still_accepted(self):
        cfg = DeepanCodeConfig.model_validate({
            "default_provider": "openrouter",
            "providers": {},
        })
        assert cfg.default_provider == "openrouter"
