"""
HTTP Client for DeepanCode.
Handles communication with OpenRouter and OpenCode Zen APIs.
Extracts detailed token usage matching OpenCode's model.
Includes retry logic, connection pooling, and retry budget for transient provider errors.
"""

import json
import os
import random
import time
import httpx
import logging
import platform
import argparse
from typing import Dict, List, Any, Generator, Optional

from deepans_code.config import config_mgr
from deepans_code.models import PROVIDERS, get_provider_for_model, get_model_cost, get_model_context_window
from deepans_code.token_usage import (
    TokenUsageTracker, TokenBreakdown, CostInfo, MessageUsage,
    safe_number, get_cache_tokens, calculate_cost, token_tracker
)

logger = logging.getLogger("deepans_code.client")

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY_BASE = 2  # seconds
RETRYABLE_STATUS_CODES = {500, 501, 502, 503, 504, 507, 508}
MAX_RETRY_BUDGET = 10  # max consecutive-failure retries before giving up

# Provider fallback mapping
PROVIDER_FALLBACK = {
    "opencode": "openrouter",
    "openrouter": "opencode",
}


class LLMClient:
    """Unified client for OpenRouter and OpenCode Zen APIs with retry logic."""

    def __init__(self):
        self.timeout = 60.0
        self._client = None
        self._consecutive_failures = {}  # Track consecutive failures per provider
        self._cooldown_until = {}  # Track cooldown timestamps per provider
        self._retry_budget = 0  # Track total retries in this session
        self._request_count = 0
        self._total_latency = 0.0

    def _get_headers(self, provider):
        """Get API headers for a provider."""
        api_key = config_mgr.get_api_key(provider)
        if not api_key:
            raise ValueError(f"No API key configured for {provider}. Use /connect {provider} <key>")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        if provider == "openrouter":
            headers["HTTP-Referer"] = "https://deepancode.ai"
            headers["X-Title"] = "DeepanCode"

        return headers

    def _normalize_provider(self, provider):
        """Normalize provider name to canonical lowercase form."""
        cleaned = (provider or "").strip()
        normalized = cleaned.lower().replace("-", "").replace("_", "").replace(" ", "")
        if normalized in ("opencode", "opencodezen"):
            return "opencode"
        if normalized == "openrouter":
            return "openrouter"
        # Unknown providers: return the cleaned lowercase form so registry
        # lookups (PROVIDERS keys) and header branches match consistently,
        # never sending one provider's key under another provider's URL.
        return normalized or cleaned

    def _get_api_url(self, provider):
        """Get API URL for a provider."""
        prov_data = PROVIDERS.get(provider, {})
        url = prov_data.get("api_base")
        if not url:
            logger.warning(f"Unknown provider '{provider}'; falling back to OpenRouter base URL")
            url = "https://openrouter.ai/api/v1"
        return url

    def _get_model_id(self, model_id, provider):
        """Format model ID based on provider."""
        return model_id

    def _swap_model_for_provider(self, model_id, new_provider):
        """Pick an appropriate model when switching providers."""
        if new_provider == "openrouter":
            if "/" not in model_id:
                return "openrouter/free"
            return model_id
        if new_provider == "opencode":
            from deepans_code.models import get_default_model_for_provider
            return get_default_model_for_provider("opencode")
        return model_id

    def _get_client(self):
        """Get or create reusable HTTP client with connection pooling."""
        if self._client is None or self._client.is_closed:
            limits = httpx.Limits(
                max_connections=10,
                max_keepalive_connections=5,
                keepalive_expiry=30,
            )
            # httpx.HTTPTransport has no `retries` kwarg; retries are
            # handled explicitly by the caller's retry loop with backoff.
            transport = httpx.HTTPTransport(limits=limits)
            self._client = httpx.Client(
                timeout=self.timeout,
                transport=transport,
                # Do not forward Authorization across hosts on redirect.
                follow_redirects=False,
            )
        return self._client

    def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            self._client.close()

    def _check_retry_budget(self) -> bool:
        """Check if we've exceeded our retry budget for this session."""
        if self._retry_budget >= MAX_RETRY_BUDGET:
            logger.warning(f"Retry budget exhausted: {self._retry_budget}/{MAX_RETRY_BUDGET}")
            return False
        return True

    def _increment_retry_budget(self):
        """Track a retry."""
        self._retry_budget += 1
        logger.debug(f"Retry budget: {self._retry_budget}/{MAX_RETRY_BUDGET}")

    def get_stats(self) -> Dict[str, Any]:
        """Get client performance statistics."""
        return {
            "request_count": self._request_count,
            "total_latency": round(self._total_latency, 2),
            "avg_latency": round(self._total_latency / max(self._request_count, 1), 2),
            "retry_budget_used": self._retry_budget,
            "retry_budget_remaining": MAX_RETRY_BUDGET - self._retry_budget
        }

    def _is_retryable_error(self, error: Exception) -> bool:
        """Check if an error is retryable (transient network/server issues only)."""
        if isinstance(error, httpx.HTTPStatusError):
            # 429 = rate limited -> retryable with backoff (handled in caller)
            if error.response.status_code == 429:
                return True
            return error.response.status_code in RETRYABLE_STATUS_CODES
        if isinstance(error, (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout)):
            return True
        error_str = str(error).lower()
        if any(code in error_str for code in ["400", "401", "403", "404", "422"]):
            return False
        return any(phrase in error_str for phrase in [
            "timeout", "connection", "reset", "refused", "timed out"
        ])

    def _get_retry_delay(self, attempt: int) -> float:
        """Calculate retry delay with exponential backoff + jitter (monotonic, capped)."""
        base = RETRY_DELAY_BASE ** min(max(int(attempt), 0), 5)
        return base + random.uniform(0, 1.0)

    def _sleep_backoff(self, attempt: int, error: Exception) -> None:
        capped = min(max(int(attempt), 0), 5)
        is_429 = isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 429
        if is_429:
            time.sleep(min(5 * (2 ** (capped % MAX_RETRIES)), 60) + random.uniform(0, 1.0))
        else:
            time.sleep(self._get_retry_delay(capped))

    def _resolve_active(self, model: str, provider: str):
        provider = self._normalize_provider(provider)
        active = self._get_available_provider(provider)
        if active != provider:
            model = self._swap_model_for_provider(model, active)
        return model, provider, active

    def _pick_attempt_provider(self, attempt: int, active_provider: str, model: str,
                               forced: Optional[str], tried: set):
        """Shared provider-picking for both sync/stream loops. Returns (current, model, forced)."""
        if forced is not None:
            current = forced
            forced = None
            model = self._swap_model_for_provider(model, current)
            return current, model, forced
        if attempt < MAX_RETRIES:
            return active_provider, model, forced
        fallback = PROVIDER_FALLBACK.get(active_provider, "openrouter")
        try:
            if not config_mgr.get_api_key(fallback):
                return None, model, forced
        except Exception:
            return None, model, forced
        return fallback, self._swap_model_for_provider(model, fallback), forced

    def _final_error(self, provider: str, model: str, last_error) -> Exception:
        error_msg = str(last_error) if last_error else "Unknown error"
        if "429" in error_msg:
            return Exception(
                f"Rate limited (429) by {provider}. Free tier quota exhausted.\n"
                f"Wait 60+ seconds and try again, or switch model: /config model openrouter/free"
            )
        if "401" in error_msg or "403" in error_msg:
            return Exception(self._format_auth_error(provider, error_msg))
        if "400" in error_msg:
            return Exception(
                f"Bad request (400) from {provider}. Model '{model}' may not be available.\n"
                f"Try: /config model openrouter/free\n"
                f"Original error: {error_msg}"
            )
        return Exception(f"API Error: {error_msg}")

    @staticmethod
    def _format_auth_error(provider: str, error_msg: str) -> str:
        """Build a clear, actionable message for 401/403 auth failures."""
        env_var = "OPENROUTER_API_KEY" if provider == "openrouter" else "OPENCODE_API_KEY"
        return (
            f"Authentication failed (401 Unauthorized) for provider '{provider}'.\n"
            f"Your API key is missing, invalid, expired, or has no credits.\n\n"
            f"How to fix:\n"
            f"  1. Set the key:  /connect {provider} <YOUR_API_KEY>\n"
            f"     (or export {env_var}=<YOUR_API_KEY> before launching)\n"
            f"  2. Re-run your prompt.\n"
            f"  3. Or switch providers with:  /switch\n\n"
            f"Original error: {error_msg}"
        )

    def _is_provider_available(self, provider):
        """Check if a provider is available (not in cooldown)."""
        cooldown_until = self._cooldown_until.get(provider, 0)
        if time.time() < cooldown_until:
            return False
        return True

    def _mark_provider_failed(self, provider):
        """Mark a provider as failed and set cooldown."""
        self._consecutive_failures[provider] = self._consecutive_failures.get(provider, 0) + 1
        # Exponential cooldown: 30s, 60s, 120s, max 300s
        cooldown = min(30 * (2 ** (self._consecutive_failures[provider] - 1)), 300)
        self._cooldown_until[provider] = time.time() + cooldown

    def _mark_provider_success(self, provider):
        """Mark a provider as successful, reset failure count and retry budget."""
        self._consecutive_failures[provider] = 0
        self._cooldown_until[provider] = 0
        # A success proves the outage is over: reset the session retry budget
        # so long-lived sessions can't brick permanently after a storm.
        self._retry_budget = 0

    def _get_available_provider(self, preferred_provider):
        """Get an available provider, falling back if needed."""
        if self._is_provider_available(preferred_provider):
            return preferred_provider

        fallback = PROVIDER_FALLBACK.get(preferred_provider, "openrouter")
        if self._is_provider_available(fallback):
            # Only use fallback if it has a valid API key
            try:
                api_key = config_mgr.get_api_key(fallback)
                if api_key:
                    return fallback
            except Exception:
                pass

        # Both providers unavailable, try the preferred one anyway
        return preferred_provider

    def chat_completion(self, messages, tools=None, model=None, provider=None):
        """Send a chat completion request (non-streaming) with retry logic and auto-fallback."""
        from deepans_code.security import rate_limiter
        if model is None:
            model = config_mgr.get("model", "openrouter/free")
        if provider is None:
            provider = config_mgr.get("provider", "openrouter")
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages must be a non-empty list")
        if not rate_limiter.allow(f"llm:{provider}"):
            raise Exception("Rate limited (429) locally. Wait 60s before retrying.")

        provider = self._normalize_provider(provider)

        # Auto-fallback: check if provider is available
        active_provider = self._get_available_provider(provider)
        if active_provider != provider:
            model = self._swap_model_for_provider(model, active_provider)

        last_error = None
        tried_providers = set()
        forced_provider = None
        request_start = time.time()

        for attempt in range(MAX_RETRIES * 2):
            if not self._check_retry_budget():
                raise Exception("Retry budget exhausted. Try again later or use /clear.")

            if forced_provider is not None:
                current_provider = forced_provider
                forced_provider = None
                model = self._swap_model_for_provider(model, current_provider)
            elif attempt < MAX_RETRIES:
                current_provider = active_provider
            else:
                fallback = PROVIDER_FALLBACK.get(active_provider, "openrouter")
                # Don't try fallback if it has no key: keep retrying active.
                try:
                    fb_key = config_mgr.get_api_key(fallback)
                    if not fb_key:
                        current_provider = active_provider
                    else:
                        current_provider = fallback
                        model = self._swap_model_for_provider(model, current_provider)
                except Exception:
                    current_provider = active_provider

            # Skip if already tried this provider
            if current_provider in tried_providers and len(tried_providers) >= 2:
                break
            tried_providers.add(current_provider)

            try:
                headers = self._get_headers(current_provider)
                url = f"{self._get_api_url(current_provider)}/chat/completions"

                payload = {
                    "model": self._get_model_id(model, current_provider),
                    "messages": messages,
                    "temperature": 0.1,
                    "max_tokens": 4096
                }

                if tools:
                    payload["tools"] = tools
                    payload["tool_choice"] = "auto"

                http_client = self._get_client()
                response = http_client.post(url, headers=headers, json=payload)

                response.raise_for_status()
                self._mark_provider_success(current_provider)
                latency = time.time() - request_start
                self._request_count += 1
                self._total_latency += latency
                logger.debug(f"Request completed: {current_provider}/{model} in {latency:.2f}s")
                return response.json()

            except Exception as e:
                last_error = e
                self._mark_provider_failed(current_provider)
                self._increment_retry_budget()

                if not self._is_retryable_error(e):
                    fallback = PROVIDER_FALLBACK.get(current_provider, "openrouter")
                    if fallback != current_provider and fallback not in tried_providers:
                        try:
                            fb_key = config_mgr.get_api_key(fallback)
                            if fb_key:
                                forced_provider = fallback
                                continue
                        except Exception:
                            pass
                    break

                self._sleep_backoff(attempt, e)

        # All retries failed - provide helpful error message
        raise self._final_error(provider, model, last_error)

    def chat_completion_stream(self, messages, tools=None, model=None, provider=None):
        """Send a chat completion request (streaming) with retry logic and auto-fallback."""
        if model is None:
            model = config_mgr.get("model", "openrouter/free")
        if provider is None:
            provider = config_mgr.get("provider", "openrouter")

        provider = self._normalize_provider(provider)

        active_provider = self._get_available_provider(provider)
        if active_provider != provider:
            model = self._swap_model_for_provider(model, active_provider)

        last_error = None
        tried_providers = set()
        forced_provider = None
        request_start = time.time()

        for attempt in range(MAX_RETRIES * 2):
            if not self._check_retry_budget():
                raise Exception("Retry budget exhausted. Try again later or use /clear.")

            if forced_provider is not None:
                current_provider = forced_provider
                forced_provider = None
                model = self._swap_model_for_provider(model, current_provider)
            elif attempt < MAX_RETRIES:
                current_provider = active_provider
            else:
                fallback = PROVIDER_FALLBACK.get(active_provider, "openrouter")
                try:
                    fb_key = config_mgr.get_api_key(fallback)
                    if not fb_key:
                        current_provider = active_provider
                    else:
                        current_provider = fallback
                        model = self._swap_model_for_provider(model, current_provider)
                except Exception:
                    current_provider = active_provider

            # Skip if already tried this provider
            if current_provider in tried_providers and len(tried_providers) >= 2:
                break
            tried_providers.add(current_provider)

            try:
                headers = self._get_headers(current_provider)
                url = f"{self._get_api_url(current_provider)}/chat/completions"

                payload = {
                    "model": self._get_model_id(model, current_provider),
                    "messages": messages,
                    "temperature": 0.1,
                    "max_tokens": 4096,
                    "stream": True
                }

                if tools:
                    payload["tools"] = tools
                    payload["tool_choice"] = "auto"

                http_client = self._get_client()
                with http_client.stream("POST", url, headers=headers, json=payload) as response:
                    if response.status_code != 200:
                        error_detail = ""
                        try:
                            error_detail = response.read().decode()[:500]
                        except:
                            pass
                        # Raise immediately for non-200 responses
                        response.raise_for_status()

                    for line in response.iter_lines():
                        if line:
                            line = line.strip()
                            if line.startswith("data: "):
                                data = line[6:]
                                if data == "[DONE]":
                                    break
                                try:
                                    chunk = json.loads(data)
                                    yield chunk
                                except json.JSONDecodeError:
                                    continue
                self._mark_provider_success(current_provider)
                latency = time.time() - request_start
                self._request_count += 1
                self._total_latency += latency
                logger.debug(f"Stream completed: {current_provider}/{model} in {latency:.2f}s")
                return

            except Exception as e:
                last_error = e
                self._mark_provider_failed(current_provider)
                self._increment_retry_budget()

                if not self._is_retryable_error(e):
                    fallback = PROVIDER_FALLBACK.get(current_provider, "openrouter")
                    if fallback != current_provider and fallback not in tried_providers:
                        try:
                            fb_key = config_mgr.get_api_key(fallback)
                            if fb_key:
                                forced_provider = fallback
                                continue
                        except Exception:
                            pass
                    break

                self._sleep_backoff(attempt, e)

        # All retries failed
        raise self._final_error(provider, model, last_error)

    def extract_token_usage(
        self,
        response: Dict[str, Any],
        model_id: str,
        provider_id: str
    ) -> MessageUsage:
        """
        Extract detailed token usage from API response.
        Matches OpenCode's getUsage function.
        """
        cost_info = get_model_cost(model_id)
        return token_tracker.track_message(
            response=response,
            model_id=model_id,
            provider_id=provider_id,
            cost_info=cost_info
        )

    def extract_streaming_token_usage(
        self,
        chunks: List[Dict[str, Any]],
        model_id: str,
        provider_id: str
    ) -> Optional[MessageUsage]:
        """
        Extract token usage from streaming response.
        The last chunk typically contains usage information.
        """
        if not chunks:
            return None

        # Find the chunk with usage info (usually the last one)
        for chunk in reversed(chunks):
            if isinstance(chunk, dict) and isinstance(chunk.get("usage"), dict):
                return self.extract_token_usage(chunk, model_id, provider_id)

        return None


client = LLMClient()


def get_system_info() -> Dict[str, Any]:
    """Return basic system information for CLI/status use."""
    return {
        "os": platform.system(),
        "os_release": platform.release(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "cpu_count": os.cpu_count() or 1,
        "cwd": os.getcwd(),
    }


def _main_cli():
    parser = argparse.ArgumentParser(prog="client.py", description="Utility CLI for deepans_code.client")
    parser.add_argument("command", nargs="?", default="status", help="command to run (status)")
    args = parser.parse_args()

    if args.command == "status":
        print(json.dumps(get_system_info(), indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    _main_cli()
