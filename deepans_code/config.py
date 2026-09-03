"""
DeepanCode Configuration Management.
Uses Pydantic for validation and type safety.
Includes encrypted API key storage.

CONFIG PRECEDENCE (highest wins) — single source of truth:
  1. Environment variables: OPENROUTER_API_KEY, OPENCODE_API_KEY,
     DEEPANCODE_API_TOKEN, DEEPANCODE_ALLOWED_ORIGINS
  2. User config: ~/.deepans-code/config.json (AES-at-rest connectors)
  3. Repo defaults: Deepancode.json (models/limits/defaults — NEVER keys)
  4. Built-in DEFAULT_CONFIG

`opencode.json` belongs to the external OpenCode tool and is NOT read
by DeepanCode at runtime.
Path: ~/.deepans-code/config.json
"""

from __future__ import annotations

import os
import json
import copy
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

logger = logging.getLogger("deepans_code.config")

try:
    from pydantic import BaseModel, Field
    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False

CONFIG_DIR = Path.home() / ".deepans-code"
CONFIG_FILE = CONFIG_DIR / "config.json"
DEEPANCODE_JSON = Path(__file__).parent.parent / "Deepancode.json"

# Documented precedence (see module docstring). Exposed for tests/docs.
CONFIG_PRECEDENCE = ("env", "user_config", "deepancode_json", "defaults")
# Placeholder values that must never be treated as real keys.
PLACEHOLDER_KEYS = {"", "sk-or-...", "oc_...", "sk-...", "xxx", "changeme"}


# ============================================================================
# Pydantic Models (if available) or fallback dicts
# ============================================================================

if PYDANTIC_AVAILABLE:
    # Strict: extra="forbid" on every model so typos and schema drift fail
    # loudly at load time instead of being silently dropped. camelCase
    # aliases match Deepancode.json on disk; populate_by_name keeps
    # snake_case working for Python callers.
    class _StrictBase(BaseModel):
        model_config = {"populate_by_name": True, "extra": "forbid"}

    class CurrentUsage(_StrictBase):
        tokens_used: int = 0
        daily_used: int = 0
        monthly_used: int = 0
        last_reset: Optional[str] = None
        requests_made: int = 0

    class TokenUsageScheme(_StrictBase):
        enabled: bool = True
        daily_token_limit: int = Field(default=500_000, alias="dailyTokenLimit")
        monthly_token_limit: int = Field(default=10_000_000, alias="monthlyTokenLimit")
        reset_period: str = Field(default="daily", alias="resetPeriod")
        warning_threshold: float = Field(default=0.8, alias="warningThreshold")
        current_usage: Optional[CurrentUsage] = Field(default=None, alias="currentUsage")
        fallback_provider: str = Field(default="openrouter", alias="fallbackProvider")

    class RateLimits(_StrictBase):
        requests_per_minute: Optional[int] = Field(default=None, alias="requestsPerMinute")
        requests_per_day: Optional[int] = Field(default=None, alias="requestsPerDay")

    class OpenRouterConfig(_StrictBase):
        enabled: bool = True
        base_url: str = Field(default="https://openrouter.ai/api/v1", alias="baseURL")
        api_key: Optional[str] = Field(default=None, alias="apiKey")
        default_model: str = Field(default="cohere/north-mini-code:free", alias="defaultModel")
        free_models: List[str] = Field(default_factory=lambda: [
            "openai/gpt-oss-120b:free",
            "cohere/north-mini-code:free",
            "google/gemma-4-31b-it:free"
        ], alias="freeModels")
        token_usage: Optional[TokenUsageScheme] = Field(default=None, alias="tokenUsage")
        rate_limits: Optional[RateLimits] = Field(default=None, alias="rateLimits")

    class OpenCodeZenConfig(_StrictBase):
        enabled: bool = True
        base_url: str = Field(default="https://opencode.ai/zen/v1", alias="baseURL")
        api_key: Optional[str] = Field(default=None, alias="apiKey")
        default_model: str = Field(default="big-pickle", alias="defaultModel")
        free_models: List[str] = Field(default_factory=lambda: [
            "mimo-v2.5-free",
            "nemotron-3-ultra-free",
            "north-mini-code-free",
            "deepseek-v4-flash-free",
            "big-pickle"
        ], alias="freeModels")
        token_usage: Optional[TokenUsageScheme] = Field(default=None, alias="tokenUsage")
        rate_limits: Optional[RateLimits] = Field(default=None, alias="rateLimits")

    class Providers(_StrictBase):
        openrouter: Optional[OpenRouterConfig] = None
        opencode_zen: Optional[OpenCodeZenConfig] = Field(default=None, alias="opencodeZen")

    class ModelConfig(_StrictBase):
        provider: str
        model_id: str = Field(alias="modelId")
        max_tokens: Optional[int] = Field(default=None, alias="maxTokens")
        context_window: Optional[int] = Field(default=None, alias="contextWindow")
        token_usage: Optional[TokenUsageScheme] = Field(default=None, alias="tokenUsage")

    class AgentConfig(_StrictBase):
        name: str = "DeepanCode Terminal Agent"
        system_prompt: Optional[str] = Field(default=None, alias="systemPrompt")
        max_history: int = Field(default=20, alias="maxHistory")
        temperature: float = 0.6
        auto_switch_provider: bool = Field(default=True, alias="autoSwitchProvider")

    class UiConfig(_StrictBase):
        theme: str = "dark"
        show_token_usage: bool = Field(default=True, alias="showTokenUsage")
        show_rate_limits: bool = Field(default=True, alias="showRateLimits")

    class DeepanCodeConfig(_StrictBase):
        schema_: Optional[str] = Field(default=None, alias="$schema")
        version: str = "1.0.0"
        default_provider: str = Field(default="openrouter", alias="defaultProvider")
        default_model: str = Field(default="cohere/north-mini-code:free", alias="defaultModel")
        providers: Optional[Providers] = None
        models: Dict[str, ModelConfig] = Field(default_factory=dict)
        token_usage: Optional[TokenUsageScheme] = Field(default=None, alias="tokenUsage")
        agent: Optional[AgentConfig] = None
        ui: Optional[UiConfig] = None
else:
    # Fallback when Pydantic is not installed
    CurrentUsage = None
    TokenUsageScheme = None
    RateLimits = None
    OpenRouterConfig = None
    OpenCodeZenConfig = None
    Providers = None
    ModelConfig = None
    AgentConfig = None
    UiConfig = None
    DeepanCodeConfig = None


# ============================================================================
# Default Configuration
# ============================================================================

DEFAULT_CONFIG = {
    "app_name": "DeepanCode",
    "provider": "openrouter",
    "model": "openrouter/free",
    "effort": "medium",
    "mode": "code",
    "agent": "build",
    "thinking": True,
    "theme": "default",
    "connectors": {
        "openrouter": "",
        "opencode": "",
        "google": "",
        "mistral": "",
        "deepseek": "",
        "alibaba": "",
        "cohere": "",
        "ai21": "",
        "xai": "",
        "moonshot": "",
        "zhipu": "",
        "baichuan": "",
        "minimax": "",
        "01ai": "",
        "stepfun": "",
        "anthropic": "",
        "openai": "",
        "groq": "",
        "cerebras": "",
        "sambanova": "",
        "nvidia": "",
        "together": "",
        "fireworks": "",
        "deepinfra": "",
        "novita": "",
        "chutes": "",
        "siliconflow": "",
        "nebius": "",
        "kluster": "",
        "parasail": "",
        "pollinations": "",
        "llm7": "",
        "kilo": "",
        "airforce": "",
        "anyapi": "",
        "cloudflare": "",
        "github": "",
        "scaleway": "",
        "ovhcloud": "",
        "modal": "",
        "volcengine": "",
        "baidu": "",
        "iflytek": "",
        "tencent": "",
        "modelscope": "",
        "ollama": "",
        "lmstudio": "",
        "vllm": "",
        "replicate": "",
        "huggingface": "",
        "databricks": "",
        "anyscale": "",
    },
    "token_usage": {
        "enabled": True,
        "daily_token_limit": 500000,
        "monthly_token_limit": 10000000,
        "reset_period": "daily",
        "warning_threshold": 0.8,
        "current_usage": {
            "tokens_used": 0,
            "last_reset": None,
            "requests_made": 0
        },
        "fallback_provider": "openrouter"
    },
    "rate_limits": {
        "requests_per_minute": 20,
        "requests_per_day": 50
    },
    "mcp_servers": {
        "filesystem": {
            "enabled": True,
            "type": "stdio",
            "command": "python3",
            "args": ["-m", "deepans_code.tools"]
        }
    }
}


# ============================================================================
# Helper Functions
# ============================================================================

def load_deepancode_json():
    """Load provider/model configuration from Deepancode.json."""
    try:
        if DEEPANCODE_JSON.exists():
            with open(DEEPANCODE_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"Warning: Could not load Deepancode.json: {e}")
    return {}


def get_provider_config(provider_name):
    """Get provider configuration from Deepancode.json."""
    dc_config = load_deepancode_json()
    providers = dc_config.get("providers", {})
    normalized = provider_name.lower().replace("-", "").replace("_", "").replace(" ", "")
    for key, value in providers.items():
        key_normalized = key.lower().replace("-", "").replace("_", "").replace(" ", "")
        if key_normalized == normalized:
            return value
    return {}


def get_free_models_from_json(provider_name):
    """Get free models list from Deepancode.json."""
    provider_config = get_provider_config(provider_name)
    return provider_config.get("freeModels", [])


def load_config(path="Deepancode.json"):
    """Load and validate Deepancode.json configuration."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if DeepanCodeConfig:
            return DeepanCodeConfig.model_validate(data)
        return data
    except FileNotFoundError:
        print(f"Config file not found: {path}")
        return None
    except Exception as e:
        print(f"Error loading config: {e}")
        return None


def save_config(config, path="Deepancode.json"):
    """Save configuration back to JSON file."""
    try:
        if hasattr(config, 'model_dump'):
            data = config.model_dump(by_alias=True, exclude_none=True)
        else:
            data = config

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving config: {e}")


def get_active_provider(config, provider_name=None):
    """Get the configuration for a specific provider."""
    if hasattr(config, 'default_provider'):
        name = provider_name or config.default_provider
    else:
        name = provider_name or "openrouter"

    if hasattr(config, 'providers') and config.providers:
        if name == "openrouter" and config.providers.openrouter:
            return config.providers.openrouter.model_dump() if hasattr(config.providers.openrouter, 'model_dump') else vars(config.providers.openrouter)
        elif name in ["opencodeZen", "opencode_zen", "opencode"] and config.providers.opencode_zen:
            return config.providers.opencode_zen.model_dump() if hasattr(config.providers.opencode_zen, 'model_dump') else vars(config.providers.opencode_zen)

    return get_provider_config(name)


def get_free_models(config, provider_name=None):
    """Get list of free models for a provider."""
    provider = get_active_provider(config, provider_name)
    return provider.get("free_models", [])


# ============================================================================
# Token Usage Manager
# ============================================================================

class TokenUsageManager:
    """Manages token usage tracking and limits."""

    def __init__(self, config_data):
        self.config = config_data.get("token_usage", DEFAULT_CONFIG["token_usage"])

    def get_usage(self):
        """Get current token usage (tokens_used kept as daily alias for compat)."""
        usage = self.config.get("current_usage", {
            "daily_used": 0,
            "monthly_used": 0,
            "last_reset": None,
            "requests_made": 0
        })
        if "daily_used" in usage and "tokens_used" not in usage:
            usage = {**usage, "tokens_used": usage.get("daily_used", 0)}
        return usage

    def track_usage(self, tokens):
        """Track token usage (separate daily/monthly counters, periodic reset)."""
        usage = self.get_usage()
        now = datetime.now()
        try:
            last = datetime.fromisoformat(usage["last_reset"]) if usage.get("last_reset") else None
        except ValueError:
            last = None
        if "daily_used" not in usage or "monthly_used" not in usage:
            legacy = usage.pop("tokens_used", 0) or 0  # migrate old schema once
            usage.setdefault("daily_used", legacy)
            usage.setdefault("monthly_used", legacy)
        if last is None or last.date() != now.date():
            usage["daily_used"] = 0
        if last is None or (last.year, last.month) != (now.year, now.month):
            usage["monthly_used"] = 0
        usage["daily_used"] = usage.get("daily_used", 0) + tokens
        usage["monthly_used"] = usage.get("monthly_used", 0) + tokens
        usage["requests_made"] = usage.get("requests_made", 0) + 1
        usage["last_reset"] = now.isoformat()
        usage["tokens_used"] = usage["daily_used"]  # compat alias
        self.config["current_usage"] = usage

    def check_limit(self):
        """Check if token limit is reached."""
        usage = self.get_usage()
        daily_used = usage.get("daily_used", usage.get("tokens_used", 0))
        monthly_used = usage.get("monthly_used", daily_used)
        daily_limit = self.config.get("daily_token_limit", 500000)
        monthly_limit = self.config.get("monthly_token_limit", 10000000)
        warning_threshold = self.config.get("warning_threshold", 0.8)

        daily_percentage = daily_used / daily_limit if daily_limit > 0 else 0
        monthly_percentage = monthly_used / monthly_limit if monthly_limit > 0 else 0

        return {
            "daily_used": daily_used,
            "daily_limit": daily_limit,
            "daily_percentage": daily_percentage,
            "monthly_used": monthly_used,
            "monthly_limit": monthly_limit,
            "monthly_percentage": monthly_percentage,
            "daily_warning": daily_percentage >= warning_threshold,
            "monthly_warning": monthly_percentage >= warning_threshold,
            "daily_exceeded": daily_percentage >= 1.0,
            "monthly_exceeded": monthly_percentage >= 1.0
        }

    def get_status_display(self):
        """Get formatted status display for token usage."""
        status = self.check_limit()
        daily_pct = status["daily_percentage"] * 100
        monthly_pct = status["monthly_percentage"] * 100
        daily_bar = self._make_progress_bar(daily_pct)
        monthly_bar = self._make_progress_bar(monthly_pct)

        warning = ""
        if status["daily_exceeded"]:
            warning = "\nDAILY LIMIT EXCEEDED!"
        elif status["daily_warning"]:
            warning = "\nWarning: Approaching daily limit"
        elif status["monthly_exceeded"]:
            warning = "\nMONTHLY LIMIT EXCEEDED!"
        elif status["monthly_warning"]:
            warning = "\nWarning: Approaching monthly limit"

        return f"""Token Usage:
  Daily:   {daily_bar} {daily_pct:.1f}% ({status['daily_used']:,}/{status['daily_limit']:,})
  Monthly: {monthly_bar} {monthly_pct:.1f}% ({status['monthly_used']:,}/{status['monthly_limit']:,})
  Requests: {self.get_usage()['requests_made']:,}{warning}"""

    def _make_progress_bar(self, percentage, length=20):
        """Create a visual progress bar."""
        filled = int(length * min(percentage, 1.0))
        empty = length - filled
        return f"[{'#' * filled}{'-' * empty}]"


# ============================================================================
# Config Manager
# ============================================================================

class ConfigManager:
    def __init__(self):
        self._ensure_config()
        self.config = self.load()
        self.token_usage = TokenUsageManager(self.config)
        self._load_deepancode_config()

    def _load_deepancode_config(self):
        """Load Deepancode.json defaults (precedence level 3: never keys).

        Only non-sensitive defaults (defaultModel, tokenUsage limits) are
        merged, and only when the user config has no explicit value.
        Plaintext apiKey entries are always ignored (fail-closed).
        """
        dc_config = load_deepancode_json()
        if dc_config:
            if "providers" in dc_config:
                for prov_name, prov_data in dc_config["providers"].items():
                    key = prov_name.lower().replace("-", "").replace("_", "")
                    # Normalize "opencodezen" -> "opencode" to match CLI/connector keys
                    if key == "opencodezen":
                        key = "opencode"
                    # Never copy plaintext apiKey into live config (would bypass
                    # AES-at-rest). Keys must come from env or /connect (encrypted).
                    raw = (prov_data.get("apiKey", "") or "").strip()
                    if raw and raw not in PLACEHOLDER_KEYS:
                        logger.warning(
                            f"Ignoring plaintext apiKey for '{key}' in Deepancode.json; "
                            "set it via /connect or env var instead."
                        )

            if "defaultModel" in dc_config:
                # Repo default only fills in when the key is absent entirely
                # (never overrides user config or builtin defaults).
                self.config.setdefault("model", dc_config["defaultModel"])

            if "tokenUsage" in dc_config:
                # Repo values are defaults (precedence 3): only fill keys the
                # user config does not already define — never overwrite.
                tu = self.config.setdefault("token_usage", {})
                repo_tu = dc_config["tokenUsage"] or {}
                tu.setdefault("daily_token_limit", repo_tu.get("dailyTokenLimit", 1000000))
                tu.setdefault("monthly_token_limit", repo_tu.get("monthlyTokenLimit", 20000000))
                tu.setdefault("warning_threshold", repo_tu.get("warningThreshold", 0.85))

    def _ensure_config(self):
        """Ensure config directory and file exist (restricted perms)."""
        from deepans_code.permissions import restrict_dir, restrict_file
        if not CONFIG_DIR.exists():
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        restrict_dir(CONFIG_DIR)
        if not CONFIG_FILE.exists():
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, indent=2)
            restrict_file(CONFIG_FILE)

    def load(self):
        """Load configuration from disk."""
        try:
            if not CONFIG_FILE.exists():
                return copy.deepcopy(DEFAULT_CONFIG)
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = copy.deepcopy(DEFAULT_CONFIG)
            for key, value in data.items():
                if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                    merged[key].update(value)
                else:
                    merged[key] = value
            if "connectors" not in merged:
                merged["connectors"] = {}
            if "token_usage" not in merged:
                merged["token_usage"] = copy.deepcopy(DEFAULT_CONFIG["token_usage"])
            return merged
        except (OSError, json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Could not load config, using defaults: {e}")
            return copy.deepcopy(DEFAULT_CONFIG)

    def save(self):
        """Save configuration to disk (atomic write to survive crashes)."""
        try:
            if not CONFIG_DIR.exists():
                CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            tmp = CONFIG_FILE.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(tmp, CONFIG_FILE)
            from deepans_code.permissions import restrict_file as _restrict
            _restrict(CONFIG_FILE)
        except Exception as e:
            print(f"Warning: Failed to save config: {e}")

    def get_api_key(self, provider=None):
        """Get API key for a provider (decrypts if encrypted)."""
        if provider is None:
            provider = self.config.get("provider", "openrouter")
        provider = provider.lower()

        # Check environment variables first
        if provider == "openrouter":
            env_key = os.environ.get("OPENROUTER_API_KEY")
            if env_key:
                return env_key
        elif provider in ["opencode", "opencodezen"]:
            env_key = os.environ.get("OPENCODE_API_KEY")
            if env_key:
                return env_key

        # Check user config (with decryption)
        key = self.config.get("connectors", {}).get(provider, "")
        if key and key.strip() not in PLACEHOLDER_KEYS:
            if key.startswith(("aes:", "enc:")):
                try:
                    from deepans_code.security import APIKeyEncryption
                    enc = APIKeyEncryption()
                    return enc.decrypt(key)
                except (ValueError, RuntimeError, OSError) as e:
                    logger.error(f"Stored API key for '{provider}' could not be decrypted: {e}")
                    return ""
            return key

        # Plaintext Deepancode.json fallback removed: it bypassed encryption.
        # Set keys via /connect (AES-at-rest) or env vars.
        return ""

    def set_connector(self, provider, api_key):
        """Save API key for a provider (encrypts at rest, fail-closed)."""
        if "connectors" not in self.config:
            self.config["connectors"] = {}

        clean_key = api_key.strip()
        clean_key = clean_key.strip('"\'')
        if clean_key.lower().startswith("bearer "):
            clean_key = clean_key[7:].strip()
        if len(clean_key) < 8 or any(c.isspace() for c in clean_key):
            raise ValueError("API key looks invalid (too short or contains whitespace)")

        # Encrypt the key before storing. Fail closed: never persist
        # plaintext if encryption is unavailable.
        from deepans_code.security import APIKeyEncryption
        enc = APIKeyEncryption()
        try:
            encrypted = enc.encrypt(clean_key)
        except RuntimeError as e:
            logger.error(f"API key not saved: {e}")
            raise
        except (ValueError, OSError) as e:
            logger.error(f"API key encryption failed, not saving: {e}")
            raise
        self.config["connectors"][provider.lower()] = encrypted

        self.save()

    def get(self, key, default=None):
        """Get a config value."""
        return self.config.get(key, default)

    def set(self, key, value):
        """Update config in memory and save if critical."""
        self.config[key] = value
        if key in ("connectors", "model", "provider", "theme", "thinking", "effort", "mode", "agent"):
            self.save()

    def track_token_usage(self, tokens):
        """Track token usage for a request."""
        self.token_usage.track_usage(tokens)
        self.config["token_usage"] = self.token_usage.config
        self.save()

    def check_token_limit(self):
        """Check token usage limits."""
        return self.token_usage.check_limit()

    def get_token_usage_display(self):
        """Get formatted token usage display."""
        return self.token_usage.get_status_display()


# Lazy singleton: no filesystem I/O at import time. Use get_config() in
# new code; `config_mgr` is a lazy proxy for backwards compatibility.
_config_instance: Optional["ConfigManager"] = None


def get_config() -> "ConfigManager":
    global _config_instance
    if _config_instance is None:
        _config_instance = ConfigManager()
    return _config_instance


class _LazyConfigProxy:
    def _real(self) -> "ConfigManager":
        return get_config()

    def __getattr__(self, name):
        return getattr(self._real(), name)


config_mgr = _LazyConfigProxy()  # type: ignore
