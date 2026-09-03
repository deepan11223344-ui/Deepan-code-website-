"""
Live-gateway e2e smoke: hits the real provider /models endpoint.

Skipped unless DEEPANCODE_LIVE_TEST=1 AND a provider key is set.
Read-only (no tokens spent, no chat completion). Run in CI nightly or
manually:  DEEPANCODE_LIVE_TEST=1 OPENROUTER_API_KEY=... pytest -m e2e
"""

import os

import pytest

pytestmark = pytest.mark.e2e


def _live_config():
    if os.environ.get("DEEPANCODE_LIVE_TEST") != "1":
        return None
    key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENCODE_API_KEY")
    if not key:
        return None
    provider = "openrouter" if os.environ.get("OPENROUTER_API_KEY") else "opencode"
    return provider, key


@pytest.fixture
def live():
    cfg = _live_config()
    if cfg is None:
        pytest.skip("Live gateway smoke requires DEEPANCODE_LIVE_TEST=1 + API key")
    return cfg


def test_live_models_endpoint(live):
    import httpx
    from deepans_code.models import PROVIDERS

    provider, key = live
    base = PROVIDERS.get(provider, {}).get("api_base", "https://openrouter.ai/api/v1")
    with httpx.Client(timeout=20) as client:
        resp = client.get(
            f"{base}/models",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert resp.status_code == 200, f"Gateway returned {resp.status_code}"
    data = resp.json()
    models = data.get("data", data)
    assert isinstance(models, (list, dict)) and len(models) > 0


def test_live_key_authenticates(live):
    """Same endpoint, wrong key must NOT authenticate (guards false-green)."""
    import httpx
    from deepans_code.models import PROVIDERS

    provider, _ = live
    base = PROVIDERS.get(provider, {}).get("api_base", "https://openrouter.ai/api/v1")
    with httpx.Client(timeout=20) as client:
        resp = client.get(
            f"{base}/models",
            headers={"Authorization": "Bearer invalid-key-for-smoke-test"},
        )
    assert resp.status_code in (401, 403)
