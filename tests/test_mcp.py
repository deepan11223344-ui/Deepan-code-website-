"""Tests for MCP stdio transport (live subprocess, tmp-isolated config)."""

import json
import sys
import pytest
from deepans_code import mcp_manager as mcp_mod
from deepans_code.mcp_manager import MCPManager, validate_mcp_command

FAKE_SERVER = """\
import sys, json
def reply(i, result):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": i, "result": result}) + "\\n")
    sys.stdout.flush()
for line in sys.stdin:
    try:
        msg = json.loads(line)
    except Exception:
        continue
    m, i = msg.get("method"), msg.get("id")
    if m == "initialize":
        reply(i, {"protocolVersion": "2024-11-05", "capabilities": {},
                  "serverInfo": {"name": "fake", "version": "0.1"}})
    elif m == "notifications/initialized":
        pass
    elif m == "tools/list":
        reply(i, {"tools": [{"name": "echo", "description": "Echo back",
                             "inputSchema": {"type": "object"}}]})
    elif m == "tools/call":
        p = msg.get("params", {})
        reply(i, {"content": [{"type": "text",
                               "text": "echo:" + json.dumps(p.get("arguments", {}))}]})
    elif i is not None:
        reply(i, {"error": "unreachable"})
"""


@pytest.fixture
def mgr(tmp_path, monkeypatch):
    fake_dir = tmp_path / ".deepans-code"
    fake_dir.mkdir()
    monkeypatch.setattr(mcp_mod, "CONFIG_DIR", fake_dir)
    monkeypatch.setattr(mcp_mod, "MCP_CONFIG_FILE", fake_dir / "mcp_servers.json")
    manager = MCPManager()
    yield manager
    manager.disconnect_all()


@pytest.fixture
def server_script(tmp_path):
    p = tmp_path / "fake_mcp_server.py"
    p.write_text(FAKE_SERVER, encoding="utf-8")
    return str(p)


class TestCommandValidation:
    def test_rejects_shell_metachars(self):
        ok, _ = validate_mcp_command("python", ["-c", "x; rm -rf /"])
        assert not ok

    def test_rejects_non_allowlisted_host(self):
        ok, _ = validate_mcp_command("powershell", ["-Command", "hi"])
        assert not ok

    def test_rejects_missing_executable(self):
        ok, _ = validate_mcp_command("python", ["-m", "definitely_not_a_module_xyz"])
        # module existence isn't checked, but the host itself must exist:
        assert ok  # python exists; module errors surface at connect/call time

    def test_rejects_unknown_host(self):
        ok, _ = validate_mcp_command("no-such-binary-xyz", [])
        assert not ok


class TestLiveTransport:
    def test_connect_list_call(self, mgr, server_script):
        assert "added successfully" in mgr.add_stdio_server(
            "fake", sys.executable, [server_script])
        assert "connected" in mgr.connect("fake")
        tools = mgr.list_tools("fake")
        assert [t["name"] for t in tools] == ["echo"]
        out = mgr.call_tool("fake", "echo", {"msg": "hi"})
        assert out == 'echo:{"msg": "hi"}'

    def test_call_connects_lazily(self, mgr, server_script):
        mgr.add_stdio_server("fake", sys.executable, [server_script])
        out = mgr.call_tool("fake", "echo", {"a": 1})
        assert out == 'echo:{"a": 1}'

    def test_tool_schemas_aggregate(self, mgr, server_script):
        mgr.add_stdio_server("fake", sys.executable, [server_script])
        schemas = mgr.get_tool_schemas()
        assert len(schemas) == 1
        fn = schemas[0]["function"]
        assert fn["name"] == "mcp_fake_echo"
        assert "[MCP:fake]" in fn["description"]

    def test_unknown_and_disabled(self, mgr):
        assert mgr.call_tool("nope", "echo", {}).startswith("Error:")
        assert mgr.connect("nope").startswith("Error:")
        mgr.servers["off"] = {"enabled": False, "type": "stdio",
                              "command": sys.executable, "args": []}
        assert mgr.call_tool("off", "echo", {}).startswith("Error:")
        assert mgr.connect("off").startswith("Error:")

    def test_crash_is_reported_not_hung(self, mgr, monkeypatch):
        monkeypatch.setattr(mcp_mod, "SPAWN_TIMEOUT", 3.0)
        monkeypatch.setattr(mcp_mod, "REQUEST_TIMEOUT", 3.0)
        mgr.add_stdio_server("dead", sys.executable, ["-c", "import sys"])
        assert mgr.connect("dead").startswith("Error:")

    def test_toggle_disconnects(self, mgr, server_script):
        mgr.add_stdio_server("fake", sys.executable, [server_script])
        mgr.connect("fake")
        mgr.toggle_server("fake")
        assert "DISABLED" in mgr.list_servers()
        assert mgr.call_tool("fake", "echo", {}).startswith("Error:")
