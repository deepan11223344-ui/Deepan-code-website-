"""
MCP Server Manager for DeepanCode.
Manages Model Context Protocol (MCP) servers over stdio using JSON-RPC 2.0
(newline-delimited, per the MCP stdio transport spec).

Security: servers are spawned with ``shell=False`` (argv list, never a shell
string), commands must pass a strict allowlist check, and the executable must
resolve on PATH. Only servers explicitly added + enabled via /mcp are started.
"""

import json
import logging
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger("deepans_code.mcp")

CONFIG_DIR = Path.home() / ".deepans-code"
MCP_CONFIG_FILE = CONFIG_DIR / "mcp_servers.json"

MCP_PROTOCOL_VERSION = "2024-11-05"
SPAWN_TIMEOUT = 15.0
REQUEST_TIMEOUT = 30.0
MAX_LINE_BYTES = 4_000_000  # 4 MB cap per JSON-RPC line (DoS guard)

# Executables that may host an MCP server. Anything else is rejected unless
# explicitly passed via extra_allowed (trusted local sessions only).
# NOTE: package runners that fetch+execute remote code (npx/uvx/bunx) are
# deliberately NOT in the default set: `npx evil-pkg` would nullify the
# pinned supply chain. Pass them via extra_allowed only for trusted setups.
MCP_HOST_ALLOWLIST = {"python", "python3", "py", "node", "deno"}
MCP_REMOTE_RUNNERS = {"npx", "uvx", "bunx"}
_SHELL_METACHARS = re.compile(r"[;&|`$<>\n]|(\|\|?)|(\$\()")

_NAME_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}")


class MCPError(Exception):
    """Raised for MCP transport / protocol failures."""


class MCPClient:
    """One live stdio connection to an MCP server (JSON-RPC 2.0, NDJSON)."""

    def __init__(self, command: str, args: List[str]):
        self.command = command
        self.args = list(args or [])
        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._pending: Dict[Any, queue.Queue] = {}
        self._pending_lock = threading.Lock()
        self._req_id = 0
        self._id_lock = threading.Lock()
        self._tools: List[Dict[str, Any]] = []

    # -- lifecycle ------------------------------------------------------
    def connect(self) -> None:
        exe = shutil.which(self.command)
        if not exe:
            raise MCPError(f"Executable not found on PATH: {self.command!r}")
        try:
            self._proc = subprocess.Popen(
                [exe, *self.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                shell=False,
            )
        except OSError as e:
            raise MCPError(f"Failed to spawn MCP server: {e}")
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        try:
            result = self._request("initialize", {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "deepans-code", "version": "3.0.0"},
            }, timeout=SPAWN_TIMEOUT)
            if not isinstance(result, dict):
                raise MCPError("Bad initialize response from MCP server")
            server_version = result.get("protocolVersion", "")
            if server_version and server_version != MCP_PROTOCOL_VERSION:
                logger.warning(f"MCP protocol version mismatch: server={server_version}")
            self._notify("notifications/initialized", {})
            self._tools = self._fetch_tools()
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    proc.kill()
                except OSError:
                    pass
        with self._pending_lock:
            for q in self._pending.values():
                try:
                    q.put_nowait({"__transport_closed": True})
                except queue.Full:
                    pass
            self._pending.clear()

    @property
    def connected(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # -- tools ----------------------------------------------------------
    def list_tools(self) -> List[Dict[str, Any]]:
        return [dict(t) for t in self._tools]

    def call_tool(self, name: str, arguments: Dict[str, Any] = None) -> Any:
        if not self.connected:
            raise MCPError("MCP server is not connected")
        return self._request("tools/call", {
            "name": name,
            "arguments": arguments or {},
        }, timeout=REQUEST_TIMEOUT)

    # -- JSON-RPC plumbing ----------------------------------------------
    def _next_id(self) -> int:
        with self._id_lock:
            self._req_id += 1
            return self._req_id

    def _send(self, payload: Dict[str, Any]) -> None:
        assert self._proc and self._proc.stdin
        line = json.dumps(payload, ensure_ascii=False)
        try:
            self._proc.stdin.write(line + "\n")
            self._proc.stdin.flush()
        except (OSError, ValueError) as e:
            raise MCPError(f"MCP server stdin write failed: {e}")

    def _request(self, method: str, params: Dict[str, Any], timeout: float) -> Any:
        req_id = self._next_id()
        q: queue.Queue = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._pending[req_id] = q
        self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        try:
            msg = q.get(timeout=timeout)
        except queue.Empty:
            with self._pending_lock:
                self._pending.pop(req_id, None)
            raise MCPError(f"MCP request '{method}' timed out after {timeout}s")
        if isinstance(msg, dict) and msg.get("__transport_closed"):
            raise MCPError("MCP server closed the connection")
        if not isinstance(msg, dict) or msg.get("id") != req_id:
            raise MCPError(f"Malformed MCP response for '{method}'")
        if "error" in msg:
            err = msg["error"]
            raise MCPError(f"MCP error {err.get('code')}: {err.get('message')}")
        return msg.get("result")

    def _notify(self, method: str, params: Dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _fetch_tools(self) -> List[Dict[str, Any]]:
        try:
            result = self._request("tools/list", {}, timeout=REQUEST_TIMEOUT)
        except MCPError as e:
            logger.warning(f"MCP tools/list failed: {e}")
            return []
        tools = (result or {}).get("tools", []) if isinstance(result, dict) else []
        return [t for t in tools if isinstance(t, dict) and t.get("name")]

    def _read_loop(self) -> None:
        proc = self._proc
        stdout = proc.stdout if proc else None
        if stdout is None:
            return
        while True:
            try:
                line = stdout.readline()
            except (OSError, ValueError):
                break
            if not line:
                break  # EOF: server exited
            if len(line.encode("utf-8", errors="ignore")) > MAX_LINE_BYTES:
                logger.warning("MCP line exceeded size cap; skipping")
                continue
            try:
                msg = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue  # ignore non-JSON stdout noise
            if not isinstance(msg, dict):
                continue
            if "method" in msg and "result" not in msg and "error" not in msg:
                # Server -> client request (e.g. roots/list): we support no
                # server-initiated methods, so answer Method-not-found instead
                # of hanging the server.
                if msg.get("id") is not None and self._proc and self._proc.stdin:
                    try:
                        self._proc.stdin.write(json.dumps({
                            "jsonrpc": "2.0", "id": msg["id"],
                            "error": {"code": -32601, "message": "Method not found"},
                        }) + "\n")
                        self._proc.stdin.flush()
                    except (OSError, ValueError):
                        break
                continue
            req_id = msg.get("id")
            if req_id is not None:
                with self._pending_lock:
                    q = self._pending.pop(req_id, None)
                if q is not None:
                    try:
                        q.put_nowait(msg)
                    except queue.Full:
                        pass
            # else: server notification — nothing to do for now
        # EOF / crash: unblock waiters and mark closed
        with self._pending_lock:
            for q in self._pending.values():
                try:
                    q.put_nowait({"__transport_closed": True})
                except queue.Full:
                    pass
            self._pending.clear()


def validate_mcp_command(command: str, args: List[str], extra_allowed=None) -> tuple:
    """Return (ok, reason). Blocks shells, metachars, and missing executables."""
    if not command or len(command) > 256:
        return False, "invalid command"
    if _SHELL_METACHARS.search(command) or any(_SHELL_METACHARS.search(a) for a in (args or [])):
        return False, "shell metacharacters not allowed in MCP command/args"
    first = command.strip().lower().split("/")[-1].split("\\")[-1]
    if first.endswith((".exe", ".cmd", ".bat")):
        first = first.rsplit(".", 1)[0]
    allowed = MCP_HOST_ALLOWLIST | (set(extra_allowed or set()))
    if first not in allowed:
        return False, f"host '{first}' not in MCP allowlist"
    if shutil.which(command) is None:
        return False, f"executable not found on PATH: {command}"
    if len(args or []) > 32 or any(len(a) > 1024 for a in (args or [])):
        return False, "too many or oversized args"
    return True, "ok"


class MCPManager:
    """Manages MCP server configurations + live stdio connections."""

    def __init__(self):
        self.servers = self._load()
        self._clients: Dict[str, MCPClient] = {}
        self._lock = threading.Lock()

    def _load(self):
        """Load MCP server configurations."""
        try:
            if MCP_CONFIG_FILE.exists():
                with open(MCP_CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data if isinstance(data, dict) else {}
        except Exception:
            pass
        return {}

    def _save(self):
        """Save MCP server configurations (atomic write)."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = MCP_CONFIG_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.servers, f, indent=2)
        import os as _os
        _os.replace(tmp, MCP_CONFIG_FILE)

    def list_servers(self):
        """List all configured MCP servers."""
        if not self.servers:
            return "No MCP servers configured.\n\nUsage:\n  /mcp add <name> <command> [args]\n  /mcp remove <name>\n  /mcp toggle <name>"

        lines = []
        with self._lock:
            live = set(self._clients)
        for name, config in self.servers.items():
            status = "ENABLED" if config.get("enabled", True) else "DISABLED"
            if name in live:
                status += "+LIVE"
            cmd = config.get("command", "")
            args = " ".join(config.get("args", []))
            lines.append(f"  {name}: {status}")
            lines.append(f"    Command: {cmd} {args}")

        return "\n".join(lines)

    def add_stdio_server(self, name, command, args=None):
        """Add a stdio MCP server (validated; connection is lazy)."""
        if args is None:
            args = []
        if not _NAME_RE.fullmatch(name or ""):
            return "Error: invalid server name (use letters/numbers/._-, max 64)"
        ok, reason = validate_mcp_command(command, list(args)[:32])
        if not ok:
            return f"Error: rejected MCP server ({reason})"
        self.servers[name] = {
            "enabled": True,
            "type": "stdio",
            "command": command,
            "args": list(args)[:32]
        }
        self._save()
        return f"MCP server '{name}' added successfully (connects lazily on first use)"

    def remove_server(self, name):
        """Remove an MCP server (disconnects it first)."""
        self.disconnect(name)
        if name in self.servers:
            del self.servers[name]
            self._save()
            return f"MCP server '{name}' removed"
        return f"MCP server '{name}' not found"

    def toggle_server(self, name):
        """Toggle an MCP server enabled/disabled (disables drop live links)."""
        if name in self.servers:
            current = self.servers[name].get("enabled", True)
            self.servers[name]["enabled"] = not current
            if current:
                self.disconnect(name)
            self._save()
            status = "ENABLED" if not current else "DISABLED"
            return f"MCP server '{name}' is now {status}"
        return f"MCP server '{name}' not found"

    # -- live connections ----------------------------------------------
    def connect(self, name: str) -> str:
        """Establish the stdio connection to an enabled server."""
        cfg = self.servers.get(name)
        if not cfg:
            return f"Error: MCP server '{name}' not found"
        if not cfg.get("enabled", True):
            return f"Error: MCP server '{name}' is disabled"
        with self._lock:
            client = self._clients.get(name)
            if client is not None and client.connected:
                return f"MCP server '{name}' already connected"
            client = MCPClient(cfg["command"], cfg.get("args", []))
            try:
                client.connect()
            except MCPError as e:
                return f"Error: could not connect to '{name}': {e}"
            self._clients[name] = client
            return f"MCP server '{name}' connected ({len(client.list_tools())} tools)"

    def disconnect(self, name: str) -> str:
        with self._lock:
            client = self._clients.pop(name, None)
        if client is None:
            return f"MCP server '{name}' is not connected"
        client.close()
        return f"MCP server '{name}' disconnected"

    def disconnect_all(self) -> None:
        with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for c in clients:
            c.close()

    def list_tools(self, name: str) -> List[Dict[str, Any]]:
        """Return tool descriptors, connecting lazily on first use."""
        with self._lock:
            client = self._clients.get(name)
        if client is None or not client.connected:
            err = self.connect(name)
            if err.startswith("Error:"):
                raise MCPError(err)
            with self._lock:
                client = self._clients.get(name)
        assert client is not None
        return client.list_tools()

    def call_tool(self, server_name, tool_name, arguments=None):
        """Invoke a tool on a live MCP server (connects lazily)."""
        cfg = self.servers.get(server_name)
        if not cfg:
            return f"Error: MCP server '{server_name}' not found"
        if not cfg.get("enabled", True):
            return f"Error: MCP server '{server_name}' is disabled"
        if not isinstance(arguments, dict):
            return "Error: tool arguments must be an object"
        try:
            with self._lock:
                client = self._clients.get(server_name)
            if client is None or not client.connected:
                err = self.connect(server_name)
                if err.startswith("Error:"):
                    return err
                with self._lock:
                    client = self._clients[server_name]
            result = client.call_tool(tool_name, arguments)
        except MCPError as e:
            return f"Error: MCP call failed: {e}"
        return self._format_tool_result(result)

    @staticmethod
    def _format_tool_result(result: Any) -> str:
        if isinstance(result, dict):
            content = result.get("content", result)
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict):
                        parts.append(str(block.get("text", block.get("data", block))))
                    else:
                        parts.append(str(block))
                return "\n".join(parts)[:20000]
            return json.dumps(content, ensure_ascii=False)[:20000]
        return str(result)[:20000]

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Aggregate all connected servers' tools as OpenAI-style schemas.

        Remote content is untrusted: names validated, descriptions scrubbed
        of prompt-injection patterns + truncated, schemas type-checked,
        total count capped.
        """
        from deepans_code.security import sanitizer as _sanitizer

        schemas = []
        for name, cfg in self.servers.items():
            if not cfg.get("enabled", True):
                continue
            if len(schemas) >= 100:
                logger.warning("MCP schema cap reached; skipping remaining servers")
                break
            try:
                tools = self.list_tools(name)
            except MCPError as e:
                logger.warning(f"MCP '{name}' unreachable, skipping: {e}")
                continue
            for t in tools:
                if not isinstance(t, dict):
                    continue
                raw_name = t.get("name", "")
                if not isinstance(raw_name, str) or not _NAME_RE.fullmatch(raw_name):
                    logger.warning(f"MCP '{name}': dropping tool with bad name")
                    continue
                params = t.get("inputSchema", {"type": "object"})
                if not isinstance(params, dict):
                    params = {"type": "object"}
                desc = t.get("description", "")
                if not isinstance(desc, str):
                    desc = ""
                desc = _sanitizer.sanitize(desc[:2000], strict=True)
                schemas.append({
                    "type": "function",
                    "function": {
                        "name": f"mcp_{name}_{raw_name}"[:64],
                        "description": f"[MCP:{name}] {desc}",
                        "parameters": params,
                    },
                })
        return schemas


mcp_mgr = MCPManager()
