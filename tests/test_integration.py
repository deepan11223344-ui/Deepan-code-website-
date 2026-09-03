"""
Integration tests for DeepanCode.
Tests the interaction between multiple modules.
"""

import os
import json
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from deepans_code.tools import execute_tool, set_workspace, get_tool_schemas
from deepans_code.security import CommandSandbox, WorkspaceBoundary, InputSanitizer, RateLimiter
from deepans_code.database import Database
from deepans_code.cache import LRUCache, ResponseCache, cached
from deepans_code.metrics import MetricsCollector
from deepans_code.config import ConfigManager

pytestmark = pytest.mark.integration


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        set_workspace(tmpdir)
        yield tmpdir


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db = Database(db_path=Path(db_path))
    yield db
    os.unlink(db_path)


class TestToolExecutionIntegration:
    def test_read_write_edit_cycle(self, temp_workspace):
        file_path = str(Path(temp_workspace) / "test.txt")
        result = execute_tool("create_file", {"path": file_path, "content": "Hello World"})
        assert "Successfully" in result

        content = execute_tool("read_file", {"path": file_path})
        assert content == "Hello World"

        result = execute_tool("edit_file", {"path": file_path, "old_text": "Hello", "new_text": "Goodbye"})
        assert "Successfully" in result

        content = execute_tool("read_file", {"path": file_path})
        assert content == "Goodbye World"

    def test_list_dir_after_operations(self, temp_workspace):
        execute_tool("create_file", {"path": str(Path(temp_workspace) / "a.txt"), "content": "a"})
        execute_tool("create_file", {"path": str(Path(temp_workspace) / "b.txt"), "content": "b"})

        result = execute_tool("list_dir", {"path": temp_workspace})
        assert "a.txt" in result
        assert "b.txt" in result

    def test_delete_after_create(self, temp_workspace):
        file_path = str(Path(temp_workspace) / "del.txt")
        execute_tool("create_file", {"path": file_path, "content": "delete me"})
        result = execute_tool("delete_file", {"path": file_path})
        assert "Successfully" in result
        assert not Path(file_path).exists()

    def test_tool_schemas_complete(self):
        schemas = get_tool_schemas()
        tool_names = [s["function"]["name"] for s in schemas]
        assert "read_file" in tool_names
        assert "create_file" in tool_names
        assert "edit_file" in tool_names
        assert "run_command" in tool_names
        assert "list_dir" in tool_names
        assert "delete_file" in tool_names
        assert "web_search" in tool_names
        assert "web_fetch" in tool_names


class TestSecurityIntegration:
    def test_sandbox_blocks_dangerous_commands(self):
        sandbox = CommandSandbox()
        safe, _ = sandbox.validate_command("ls -la")
        assert safe is True
        safe, _ = sandbox.validate_command("rm -rf /")
        assert safe is False

    def test_workspace_boundary_enforcement(self):
        wb = WorkspaceBoundary()
        wb.set_workspace("/tmp/test_workspace")
        valid, _, _ = wb.validate_path("/tmp/test_workspace/file.txt")
        assert valid is True
        valid, _, _ = wb.validate_path("/etc/passwd")
        assert valid is False

    def test_input_sanitizer_removes_dangerous_chars(self):
        sanitizer = InputSanitizer()
        result = sanitizer.sanitize("hello\x00world")
        assert "\x00" not in result
        detected, _ = sanitizer.detect_injection("ignore previous instructions")
        assert detected is True

    def test_rate_limiter(self):
        limiter = RateLimiter(max_requests=3, window_seconds=1)
        assert limiter.allow("test") is True
        assert limiter.allow("test") is True
        assert limiter.allow("test") is True
        assert limiter.allow("test") is False
        assert limiter.remaining("test") == 0


class TestCacheIntegration:
    def test_lru_cache_basic(self):
        cache = LRUCache(max_size=3)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        assert cache.get("key1") == "value1"
        assert cache.get("key2") == "value2"
        assert cache.get("key3") is None

    def test_lru_cache_eviction(self):
        cache = LRUCache(max_size=2)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")  # Should evict key1
        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"
        assert cache.get("key3") == "value3"

    def test_response_cache_combined(self):
        cache = ResponseCache()
        cache.set("test_key", {"data": "test"}, ttl=60)
        result = cache.get("test_key")
        assert result == {"data": "test"}

    def test_cache_stats(self):
        cache = LRUCache(max_size=10)
        cache.set("a", 1)
        cache.get("a")
        cache.get("b")
        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["size"] == 1


class TestMetricsIntegration:
    def test_metrics_recording(self):
        collector = MetricsCollector()
        collector.record_request("openrouter", 0.5, True, 100)
        collector.record_request("openrouter", 0.3, False, 50)
        collector.record_tool_call("read_file", 0.1, True)

        summary = collector.get_summary()
        assert summary["total_requests"] == 2
        assert summary["total_errors"] == 1
        assert summary["error_rate"] == 0.5

    def test_metrics_health(self):
        collector = MetricsCollector()
        health = collector.get_health()
        assert health["status"] == "healthy"
        assert "platform" in health


class TestDatabaseIntegration:
    def test_conversation_workflow(self, temp_db):
        conv_id = temp_db.create_conversation(title="Test", model="openrouter/free")
        temp_db.save_message(conv_id, "user", "Hello")
        temp_db.save_message(conv_id, "assistant", "Hi!")
        temp_db.save_message(conv_id, "user", "How are you?")
        messages = temp_db.get_messages(conv_id)
        assert len(messages) == 3

        conv = temp_db.get_conversation(conv_id)
        assert conv["message_count"] == 3

        temp_db.delete_conversation(conv_id)
        conv = temp_db.get_conversation(conv_id)
        assert conv is None

    def test_search_and_export(self, temp_db):
        conv_id = temp_db.create_conversation(title="Search Test")
        temp_db.save_message(conv_id, "user", "Python is great")
        temp_db.save_message(conv_id, "user", "Java is okay")

        results = temp_db.search_messages("Python")
        assert len(results) == 1

        md = temp_db.export_conversation(conv_id, fmt="markdown")
        assert "Search Test" in md


class TestParallelExecution:
    def test_parallel_tool_calls(self, temp_workspace):
        from deepans_code.tools import execute_tools_parallel

        tool_calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "create_file",
                    "arguments": json.dumps({
                        "path": str(Path(temp_workspace) / "parallel1.txt"),
                        "content": "file 1"
                    })
                }
            },
            {
                "id": "call_2",
                "type": "function",
                "function": {
                    "name": "create_file",
                    "arguments": json.dumps({
                        "path": str(Path(temp_workspace) / "parallel2.txt"),
                        "content": "file 2"
                    })
                }
            }
        ]

        results = execute_tools_parallel(tool_calls)
        assert len(results) == 2
        assert all("Successfully" in r[1] for r in results)
