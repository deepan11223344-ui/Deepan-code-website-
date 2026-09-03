"""Tests for web search module (fully mocked — no live network)."""

import pytest
from deepans_code import web_search
from deepans_code.web_search import search_web


@pytest.fixture(autouse=True)
def clear_search_cache():
    web_search._search_cache.clear()
    yield
    web_search._search_cache.clear()


def _fake_results(query, max_results=5):
    return [
        {"title": f"Result {i} for {query}", "url": f"https://example.com/{i}",
         "snippet": f"snippet {i}", "engine": "mock", "score": max_results - i}
        for i in range(max_results)
    ]


class TestWebSearch:
    def test_search_returns_results(self, monkeypatch):
        monkeypatch.setattr(web_search, "_search_searxng", _fake_results)
        results = search_web("Python programming", max_results=3)
        assert isinstance(results, list)
        assert len(results) == 3

    def test_search_result_structure(self, monkeypatch):
        monkeypatch.setattr(web_search, "_search_searxng", _fake_results)
        results = search_web("test query", max_results=2)
        assert len(results) == 2
        for r in results:
            assert "title" in r
            assert "url" in r
            assert "snippet" in r

    def test_search_empty_query(self, monkeypatch):
        called = []
        monkeypatch.setattr(
            web_search, "_search_searxng",
            lambda q, mr=5: called.append((q, mr)) or [])
        monkeypatch.setattr(web_search, "_search_duckduckgo", lambda q, mr=5: [])
        assert search_web("") == []
        assert called == []  # backends never hit for empty query

    def test_search_max_results(self, monkeypatch):
        monkeypatch.setattr(web_search, "_search_searxng", _fake_results)
        assert len(search_web("test", max_results=1)) == 1

    def test_search_falls_back_to_duckduckgo(self, monkeypatch):
        monkeypatch.setattr(web_search, "_search_searxng", lambda q, mr=5: [])
        monkeypatch.setattr(web_search, "_search_duckduckgo", _fake_results)
        results = search_web("fallback check", max_results=2)
        assert len(results) == 2
        assert results[0]["engine"] == "mock"

    def test_search_uses_cache(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            web_search, "_search_searxng",
            lambda q, mr=5: calls.append(1) or _fake_results(q, mr))
        search_web("cached", max_results=2)
        search_web("cached", max_results=2)
        assert len(calls) == 1
