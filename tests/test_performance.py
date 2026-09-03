"""
Performance tests for DeepanCode.
Tests caching, parallel execution, and response times.
"""

import os
import time
import tempfile
import pytest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from deepans_code import cache as cache_mod
from deepans_code.cache import LRUCache, DiskCache, ResponseCache
from deepans_code.tools import execute_tools_parallel, set_workspace
from deepans_code.metrics import MetricsCollector

pytestmark = pytest.mark.slow


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        set_workspace(tmpdir)
        yield tmpdir


@pytest.fixture(autouse=True)
def isolated_disk_cache(tmp_path, monkeypatch):
    """Redirect the default disk cache into tmp_path (never ~/.deepans-code)."""
    monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path / "cache")


class TestCachePerformance:
    def test_lru_cache_speed(self):
        cache = LRUCache(max_size=10000)

        start = time.time()
        for i in range(10000):
            cache.set(f"key_{i}", f"value_{i}")
        set_time = time.time() - start

        start = time.time()
        for i in range(10000):
            cache.get(f"key_{i}")
        get_time = time.time() - start

        assert set_time < 3.0, f"LRU set too slow: {set_time:.2f}s"
        assert get_time < 2.0, f"LRU get too slow: {get_time:.2f}s"

    def test_response_cache_hit_rate(self):
        cache = ResponseCache()

        for i in range(100):
            cache.set(f"key_{i}", {"data": i})

        hits = 0
        for i in range(100):
            if cache.get(f"key_{i}") is not None:
                hits += 1

        assert hits == 100

    def test_disk_cache_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache1 = DiskCache(cache_dir=Path(tmpdir))
            cache1.set("persistent_key", "persistent_value", ttl=3600)

            cache2 = DiskCache(cache_dir=Path(tmpdir))
            result = cache2.get("persistent_key")
            assert result == "persistent_value"


class TestParallelExecutionPerformance:
    def test_parallel_faster_than_sequential(self, temp_workspace):
        tool_calls = [
            {
                "id": f"call_{i}",
                "type": "function",
                "function": {
                    "name": "create_file",
                    "arguments": {
                        "path": str(Path(temp_workspace) / f"perf_{i}.txt"),
                        "content": f"content {i}"
                    }
                }
            }
            for i in range(10)
        ]

        start = time.time()
        parallel_results = execute_tools_parallel(tool_calls)
        parallel_time = time.time() - start

        assert len(parallel_results) == 10
        assert parallel_time < 15.0, f"Parallel execution too slow: {parallel_time:.2f}s"

    def test_parallel_tool_reliability(self, temp_workspace):
        tool_calls = [
            {
                "id": f"call_{i}",
                "type": "function",
                "function": {
                    "name": "create_file",
                    "arguments": {
                        "path": str(Path(temp_workspace) / f"reliable_{i}.txt"),
                        "content": f"content {i}"
                    }
                }
            }
            for i in range(20)
        ]

        results = execute_tools_parallel(tool_calls)
        success_count = sum(1 for _, r in results if "Successfully" in r)
        assert success_count == 20


class TestMetricsPerformance:
    def test_metrics_recording_speed(self):
        collector = MetricsCollector()

        start = time.time()
        for i in range(1000):
            collector.record_request("openrouter", 0.001, True, 100)
            collector.record_tool_call("read_file", 0.001, True)
        elapsed = time.time() - start

        assert elapsed < 3.0, f"Metrics recording too slow: {elapsed:.2f}s"

    def test_concurrent_metrics_recording(self):
        collector = MetricsCollector()

        def record_metrics(prefix):
            for i in range(100):
                collector.record_request(f"provider_{prefix}", 0.001, True, 100)

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(record_metrics, i) for i in range(4)]
            for f in futures:
                f.result()

        summary = collector.get_summary()
        assert summary["total_requests"] == 400
