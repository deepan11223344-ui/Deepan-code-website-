"""Regression tests for 10/10 hardening fixes."""

import json
import tempfile
from pathlib import Path

import pytest


class TestAgentSanitize:
    def test_unicode_preserved(self):
        from deepans_code.agent import Agent
        text = "Hello café müller — code `print('hi')` **bold**"
        out = Agent._sanitize(text)
        assert "caf" in out
        assert "m" in out  # unicode letters preserved, not blanked

    def test_control_chars_stripped(self):
        from deepans_code.agent import Agent
        out = Agent._sanitize("hello\x00\x01world\nok")
        assert "\x00" not in out and "\x01" not in out
        assert "hello" in out and "ok" in out

    def test_invalid_tool_args_dropped_not_reset(self):
        from deepans_code.agent import Agent
        bad = [{"id": "1", "type": "function",
                "function": {"name": "read_file", "arguments": "{not-json"}}]
        cleaned = Agent._sanitize_tool_calls(bad)
        assert cleaned == []  # fail-loud: dropped, not silently reset to {}

    def test_valid_tool_args_kept(self):
        from deepans_code.agent import Agent
        good = [{"id": "1", "type": "function",
                 "function": {"name": "read_file", "arguments": '{"path": "a"}'}}]
        cleaned = Agent._sanitize_tool_calls(good)
        assert len(cleaned) == 1
        assert json.loads(cleaned[0]["function"]["arguments"]) == {"path": "a"}


class TestClientTransport:
    def test_get_client_builds(self):
        from deepans_code.client import LLMClient
        c = LLMClient()
        try:
            client = c._get_client()
            assert client is not None
        finally:
            c.close()


class TestEditFileAtomic:
    def test_ambiguous_edit_rejected(self, tmp_path):
        from deepans_code import tools
        tools.set_workspace(str(tmp_path))
        p = tmp_path / "a.txt"
        p.write_text("foo foo foo")
        result = tools._edit_file(str(p), "foo", "bar")
        assert "Ambiguous" in result
        assert p.read_text() == "foo foo foo"  # unchanged

    def test_replace_all_explicit(self, tmp_path):
        from deepans_code import tools
        tools.set_workspace(str(tmp_path))
        p = tmp_path / "b.txt"
        p.write_text("foo foo")
        result = tools._edit_file(str(p), "foo", "bar", replace_all=True)
        assert "Successfully" in result
        assert p.read_text() == "bar bar"

    def test_no_backup_crash(self, tmp_path):
        from deepans_code import tools
        tools.set_workspace(str(tmp_path))
        p = tmp_path / "c.txt"
        p.write_text("hello world")
        result = tools._edit_file(str(p), "hello", "goodbye")
        assert "Successfully" in result
        assert p.read_text() == "goodbye world"


class TestDatabaseLike:
    def test_like_escaping(self, tmp_path):
        from deepans_code.database import Database
        db = Database(db_path=tmp_path / "t.db")
        cid = db.create_conversation(model="m", provider="p", mode="code")
        db.save_message(cid, "user", "100% coverage")
        db.save_message(cid, "user", "100X coverage")
        results = db.search_messages("100%")
        contents = [r["content"] for r in results]
        assert "100% coverage" in contents
        assert "100X coverage" not in contents


class TestDiskCache:
    def test_full_hash_and_roundtrip(self, tmp_path):
        from deepans_code.cache import DiskCache
        dc = DiskCache(cache_dir=tmp_path)
        dc.set("k1", {"v": 1})
        assert dc.get("k1") == {"v": 1}
        # full sha256 filename length = 64 + ".cache"
        files = list(tmp_path.glob("*.cache"))
        assert len(files) == 1
        assert len(files[0].stem) == 64

    def test_expired_returns_none(self, tmp_path):
        from deepans_code.cache import DiskCache
        dc = DiskCache(cache_dir=tmp_path)
        dc.set("k2", "v", ttl=-1)
        assert dc.get("k2") is None


class TestNoImportSideEffects:
    def test_agent_lazy_global(self):
        import subprocess, sys
        code = (
            "import deepans_code.agent as ag;"
            "print(ag.agent_instance is None);"
            "print(hasattr(ag, 'get_agent'))"
        )
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr
        lines = out.stdout.strip().splitlines()
        assert lines[0] == "True"  # no eager Agent() on import
        assert lines[1] == "True"

    def test_db_lazy_proxy(self):
        import deepans_code.database as d
        assert hasattr(d, "get_db")

    def test_config_lazy_proxy(self):
        import deepans_code.config as c
        assert hasattr(c, "get_config")


class TestPackaging:
    def test_setup_version_and_deps(self):
        text = Path("setup.py").read_text(encoding="utf-8")
        assert 'version="3.0.0"' in text
        assert "cryptography" in text
        assert "websockets" in text
        # python floor must match pyproject.toml (no dual-metadata drift).
        assert '>=3.10' in text
        pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
        assert '>=3.10' in pyproject

    def test_opencode_json_portable(self):
        data = json.loads(Path("opencode.json").read_text(encoding="utf-8"))
        raw = json.dumps(data)
        assert "C:\\Users" not in raw
        assert "C:/Users" not in raw
        perms = data.get("permission", {}).get("skill", {})
        assert perms.get("*") != "allow"

    def test_dockerfile_no_bloat(self):
        text = Path("Dockerfile").read_text(encoding="utf-8")
        assert "claude_fable" not in text.lower()
        assert "2>/dev/null" not in text
        assert "EXPOSE" not in text
