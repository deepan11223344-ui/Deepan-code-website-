"""
Model health checks for DeepanCode.
Provides health check endpoint, model status, and dynamic context windows.
"""

import time
import logging
import httpx
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger("deepans_code.model_health")

# Health check cache: {model: {"status": "healthy"|"degraded"|"down", "latency_ms": float, "last_check": float}}
_health_cache: Dict[str, Dict[str, Any]] = {}
HEALTH_CACHE_TTL = 300  # 5 minutes


def check_model_health(model_id: str, api_key: str, provider: str = "openrouter") -> Dict[str, Any]:
    if model_id in _health_cache:
        entry = _health_cache[model_id]
        if time.time() - entry.get("last_check", 0) < HEALTH_CACHE_TTL:
            return entry

    start = time.time()
    try:
        if provider == "openrouter":
            result = _check_openrouter(model_id, api_key)
        elif provider in ["opencode", "opencodezen"]:
            result = _check_opencode(model_id, api_key)
        else:
            result = {"status": "unknown", "error": "Unsupported provider"}

        latency = (time.time() - start) * 1000
        result["latency_ms"] = round(latency, 1)
        result["last_check"] = time.time()
        _health_cache[model_id] = result
        return result

    except httpx.TimeoutException:
        result = {"status": "down", "error": "Timeout", "latency_ms": 30000, "last_check": time.time()}
        _health_cache[model_id] = result
        return result
    except Exception as e:
        result = {"status": "down", "error": str(e)[:100], "latency_ms": -1, "last_check": time.time()}
        _health_cache[model_id] = result
        return result


def _check_openrouter(model_id: str, api_key: str) -> Dict[str, Any]:
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 5
                }
            )
            if resp.status_code == 200:
                return {"status": "healthy"}
            elif resp.status_code == 429:
                return {"status": "degraded", "error": "Rate limited"}
            else:
                return {"status": "down", "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"status": "down", "error": str(e)[:100]}


def _check_opencode(model_id: str, api_key: str) -> Dict[str, Any]:
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                "https://opencodezen.com/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 5
                }
            )
            if resp.status_code == 200:
                return {"status": "healthy"}
            elif resp.status_code == 429:
                return {"status": "degraded", "error": "Rate limited"}
            else:
                return {"status": "down", "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"status": "down", "error": str(e)[:100]}


def get_model_context_window(model_id: str) -> int:
    """Single source of truth: deepans_code.models registry.

    Falls back to family heuristics only for names the registry never saw.
    """
    from deepans_code.models import MODEL_CONTEXT_WINDOWS

    try:
        known = MODEL_CONTEXT_WINDOWS
    except Exception:
        known = {}
    if isinstance(known, dict) and model_id in known:
        try:
            return int(known[model_id])
        except (ValueError, TypeError):
            pass
    lowered = (model_id or "").lower()
    if "claude" in lowered:
        return 200000
    if "gpt-5" in lowered:
        return 400000
    if "gpt-4" in lowered:
        return 128000
    if "gemini" in lowered:
        return 1000000
    return 128000
    if "gpt-5" in model_id.lower():
        return 400000
    if "gemini" in model_id.lower():
        return 1000000
    return 128000


def get_all_health_status(api_key: str = None) -> Dict[str, Dict]:
    from deepans_code.models import MODEL_LIST
    results = {}
    for model in MODEL_LIST:
        model_id = model["id"]
        provider = model.get("provider", "openrouter")
        key = api_key or ""
        health = check_model_health(model_id, key, provider)
        results[model_id] = health
    return results
