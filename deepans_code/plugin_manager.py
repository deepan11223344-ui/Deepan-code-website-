"""
Plugin Manager for DeepanCode.
Sandboxed: plugins load only with a valid plugin.json manifest, bounded
counts/schemas, validated tool names, isolated lifecycle errors, and
optional HMAC manifest signatures (DEEPANCODE_PLUGIN_KEY +
DEEPANCODE_PLUGIN_POLICY=strict|permissive).
"""

import hashlib
import hmac
import importlib
import json
import logging
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from abc import ABC, abstractmethod

logger = logging.getLogger("deepans_code.plugins")

PLUGINS_DIR = Path(__file__).parent / "plugins"

# Sandbox bounds (DoS / prompt-injection / collision guards).
MAX_PLUGINS = 25
MAX_TOOL_SCHEMAS_PER_PLUGIN = 20
MAX_PROMPT_ADDON_CHARS = 8000
MAX_TOTAL_PROMPT_ADDON_CHARS = 24000
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,63}$")
_TOOL_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-+]{0,31}$")

# Signature policy: "strict" (DEFAULT) rejects unsigned manifests;
# "permissive" loads unsigned with a warning but always rejects FORGED
# (present-but-invalid) signatures. Key via DEEPANCODE_PLUGIN_KEY env. Set
# DEEPANCODE_PLUGIN_POLICY=permissive only for trusted local development.
PLUGIN_KEY_ENV = "DEEPANCODE_PLUGIN_KEY"
PLUGIN_POLICY_ENV = "DEEPANCODE_PLUGIN_POLICY"


def get_plugin_policy() -> str:
    if os.environ.get(PLUGIN_POLICY_ENV, "strict").strip().lower() == "permissive":
        return "permissive"
    return "strict"


def _canonical_manifest(data: Dict[str, Any]) -> bytes:
    """Canonical bytes covered by the manifest signature (excludes signature).

    Includes an optional code_sha256 binding: when present, the signature
    covers the hash of __init__.py, so signed code cannot be swapped
    post-signing without invalidating the signature.
    """
    tools = data.get("tools", [])
    tool_names = sorted(t for t in tools if isinstance(t, str)) if isinstance(tools, list) else []
    canon = {
        "name": data.get("name", ""),
        "version": data.get("version", ""),
        "author": data.get("author", ""),
        "tools": tool_names,
        "code_sha256": data.get("code_sha256", ""),
    }
    return json.dumps(canon, sort_keys=True, separators=(",", ":")).encode("utf-8")


def code_hash_for(plugin_dir: Path) -> str:
    """SHA256 of the plugin's __init__.py (code binding)."""
    import hashlib as _hl

    return _hl.sha256((Path(plugin_dir) / "__init__.py").read_bytes()).hexdigest()


def sign_manifest(data: Dict[str, Any], key: str = None) -> str:
    """HMAC-SHA256 hex signature for a manifest dict. Raises if no key."""
    secret = key if key is not None else os.environ.get(PLUGIN_KEY_ENV, "")
    if not secret:
        raise ValueError(f"Set {PLUGIN_KEY_ENV} to sign plugin manifests")
    return hmac.new(secret.encode("utf-8"), _canonical_manifest(data), hashlib.sha256).hexdigest()


def verify_manifest_signature(data: Dict[str, Any], key: str = None) -> tuple:
    """Verify manifest signature. Returns (ok, reason).

    - No signature field -> (False, "unsigned") — caller applies policy.
    - Valid signature -> (True, "OK").
    - Present but invalid/malformed -> (False, "forged") — always rejected.
    """
    sig = data.get("signature", "")
    if not sig:
        return False, "unsigned"
    if not isinstance(sig, str) or not re.fullmatch(r"[0-9a-f]{64}", sig):
        return False, "forged"
    secret = key if key is not None else os.environ.get(PLUGIN_KEY_ENV, "")
    if not secret:
        return False, "forged"  # cannot verify in strict contexts; treat as untrusted
    expected = hmac.new(
        secret.encode("utf-8"), _canonical_manifest(data), hashlib.sha256
    ).hexdigest()
    if hmac.compare_digest(sig, expected):
        return True, "OK"
    return False, "forged"


def _apply_signature_policy(data: Dict[str, Any], plugin_dir_name: str) -> tuple:
    """Enforce signature policy for a directory-loaded manifest.

    Returns (allowed, reason). Strict (default): unsigned rejected.
    Permissive: unsigned loads with warning. Both: forged never loads.
    """
    ok, reason = verify_manifest_signature(data)
    if ok:
        return True, "signed"
    if reason == "forged":
        logger.warning(f"Rejecting plugin '{plugin_dir_name}': invalid manifest signature")
        return False, "invalid manifest signature"
    # unsigned
    if get_plugin_policy() == "strict":
        logger.warning(f"Rejecting plugin '{plugin_dir_name}': unsigned manifest (strict policy)")
        return False, "unsigned manifest (strict policy)"
    logger.warning(f"Loading unsigned plugin '{plugin_dir_name}' (permissive policy)")
    return True, "unsigned (permissive)"


class Plugin(ABC):
    """Base class for all DeepanCode plugins."""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def version(self) -> str:
        pass

    @property
    def description(self) -> str:
        return ""

    def on_load(self):
        """Called when the plugin is loaded."""
        pass

    def on_unload(self):
        """Called when the plugin is unloaded."""
        pass

    def get_tools(self) -> List[Dict]:
        """Return additional tool schemas this plugin provides."""
        return []

    def execute_tool(self, name: str, args: Dict) -> Optional[str]:
        """Execute a tool provided by this plugin. Return None if not handled."""
        return None

    def get_system_prompt_addon(self) -> str:
        """Return additional system prompt content."""
        return ""


def _valid_manifest(data: Any) -> tuple:
    """Validate plugin.json manifest. Returns (ok, reason)."""
    if not isinstance(data, dict):
        return False, "manifest must be an object"
    name = data.get("name", "")
    version = data.get("version", "")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        return False, "invalid manifest name (a-z0-9-, 1-64 chars)"
    if not isinstance(version, str) or not _VERSION_RE.match(version):
        return False, "invalid manifest version"
    return True, "OK"


def _valid_tool_schema(schema: Any) -> tuple:
    if not isinstance(schema, dict):
        return False, "tool schema must be an object"
    fn = schema.get("function", {})
    if not isinstance(fn, dict):
        return False, "tool schema missing function"
    tname = fn.get("name", "")
    if not isinstance(tname, str) or not _TOOL_RE.match(tname):
        return False, f"invalid tool name: {tname!r}"
    return True, "OK"


class PluginManager:
    """Manages plugin loading, lifecycle, and dependency injection."""

    def __init__(self):
        self._plugins: Dict[str, Plugin] = {}
        self._tool_map: Dict[str, str] = {}  # tool_name -> plugin_name
        self._hooks: Dict[str, List[Callable]] = defaultdict(list)
        self._services: Dict[str, Any] = {}

    def register(self, plugin: Plugin) -> bool:
        """Register a plugin. Returns False if rejected by sandbox policy."""
        try:
            name = getattr(plugin, "name", "")
            version = getattr(plugin, "version", "")
        except Exception:
            logger.warning("Rejecting plugin without name/version")
            return False
        if not isinstance(name, str) or not _NAME_RE.match(name):
            logger.warning(f"Rejecting plugin with invalid name: {name!r}")
            return False
        if not isinstance(version, str) or not _VERSION_RE.match(version):
            logger.warning(f"Rejecting plugin '{name}' with invalid version")
            return False
        if name not in self._plugins and len(self._plugins) >= MAX_PLUGINS:
            logger.warning(f"Rejecting plugin '{name}': cap {MAX_PLUGINS} reached")
            return False
        if name in self._plugins:
            logger.warning(f"Plugin '{name}' already registered, replacing")
        try:
            schemas = plugin.get_tools() or []
        except Exception as e:
            logger.error(f"Plugin '{name}' get_tools() failed, rejecting: {e}")
            return False
        if len(schemas) > MAX_TOOL_SCHEMAS_PER_PLUGIN:
            logger.warning(f"Rejecting plugin '{name}': too many tool schemas")
            return False
        for schema in schemas:
            ok, reason = _valid_tool_schema(schema)
            if not ok:
                logger.warning(f"Rejecting plugin '{name}': {reason}")
                return False
            tname = schema["function"]["name"]
            owner = self._tool_map.get(tname)
            if owner is not None and owner != name:
                logger.warning(f"Rejecting plugin '{name}': tool '{tname}' owned by '{owner}'")
                return False
        self._plugins[name] = plugin
        for schema in schemas:
            self._tool_map[schema["function"]["name"]] = name
        try:
            plugin.on_load()
        except Exception as e:
            # Isolate lifecycle failures: unload, never kill the host.
            self._plugins.pop(name, None)
            for t in [s["function"]["name"] for s in schemas]:
                if self._tool_map.get(t) == name:
                    del self._tool_map[t]
            logger.error(f"Plugin '{name}' on_load failed, unloaded: {e}")
            return False
        logger.info(f"Plugin registered: {name} v{version}")
        return True

    def unregister(self, name: str):
        """Unregister a plugin."""
        plugin = self._plugins.pop(name, None)
        if plugin:
            for tool_name in list(self._tool_map):
                if self._tool_map[tool_name] == name:
                    del self._tool_map[tool_name]
            try:
                plugin.on_unload()
            except Exception as e:
                logger.error(f"Plugin '{name}' on_unload failed: {e}")
            logger.info(f"Plugin unregistered: {name}")

    def reload_plugin(self, name: str, directory: Path = None) -> bool:
        """Explicitly reload one plugin module. No implicit reloads on scan."""
        directory = directory or PLUGINS_DIR
        mod_name = f"deepans_code.plugins.{name}"
        if mod_name not in sys.modules:
            return False
        try:
            module = importlib.reload(sys.modules[mod_name])
        except Exception as e:
            logger.error(f"Failed to reload plugin '{name}': {e}")
            return False
        self.unregister(name)
        try:
            if hasattr(module, "register"):
                module.register(self)
                return True
        except Exception as e:
            logger.error(f"Failed to re-register plugin '{name}': {e}")
        return False

    def get_plugin(self, name: str) -> Optional[Plugin]:
        return self._plugins.get(name)

    def get_all_plugins(self) -> List[Plugin]:
        return list(self._plugins.values())

    def get_all_tool_schemas(self) -> List[Dict]:
        schemas = []
        for plugin in self._plugins.values():
            try:
                schemas.extend(plugin.get_tools() or [])
            except Exception as e:
                logger.error(f"Plugin '{getattr(plugin, 'name', '?')}' get_tools failed: {e}")
        return schemas[: MAX_PLUGINS * MAX_TOOL_SCHEMAS_PER_PLUGIN]

    def execute_tool(self, tool_name: str, args: Dict) -> Optional[str]:
        if not isinstance(args, dict):
            logger.warning(f"Plugin tool '{tool_name}' args must be a dict")
            return None
        plugin_name = self._tool_map.get(tool_name)
        if plugin_name:
            plugin = self._plugins.get(plugin_name)
            if plugin:
                try:
                    return plugin.execute_tool(tool_name, args)
                except Exception as e:
                    logger.error(f"Plugin '{plugin_name}' tool '{tool_name}' failed: {e}")
                    return f"Error: plugin tool failed ({e})"
        return None

    def get_system_prompt_addons(self) -> str:
        parts = []
        total = 0
        for plugin in self._plugins.values():
            try:
                addon = plugin.get_system_prompt_addon() or ""
            except Exception as e:
                logger.error(f"Plugin prompt addon failed: {e}")
                continue
            if not addon:
                continue
            addon = addon[:MAX_PROMPT_ADDON_CHARS]
            if total + len(addon) > MAX_TOTAL_PROMPT_ADDON_CHARS:
                remaining = MAX_TOTAL_PROMPT_ADDON_CHARS - total
                if remaining > 0:
                    parts.append(f"=== Plugin: {plugin.name} ===\n{addon[:remaining]}\n... (truncated)")
                break
            parts.append(f"=== Plugin: {plugin.name} ===\n{addon}")
            total += len(addon)
        return "\n\n".join(parts)

    def register_service(self, name: str, service: Any):
        self._services[name] = service

    def get_service(self, name: str) -> Optional[Any]:
        return self._services.get(name)

    def hook(self, event: str, callback: Callable):
        if not isinstance(event, str) or not event or len(event) > 64:
            raise ValueError("Invalid hook event name")
        if not callable(callback):
            raise ValueError("Hook callback must be callable")
        if len(self._hooks[event]) >= 100:
            raise ValueError("Too many hook callbacks")
        self._hooks[event].append(callback)

    def emit(self, event: str, *args, **kwargs):
        for callback in list(self._hooks.get(event, [])):
            try:
                callback(*args, **kwargs)
            except Exception as e:
                logger.error(f"Hook error ({event}): {e}")

    def load_from_directory(self, directory: Path = None) -> Dict[str, Any]:
        """Scan a plugins dir. Only dirs with valid plugin.json load.

        Returns a report {loaded, skipped, errors} — never raises, never
        executes code from dirs without a valid manifest.
        """
        from deepans_code.permissions import restrict_dir

        directory = Path(directory) if directory else PLUGINS_DIR
        report: Dict[str, Any] = {"loaded": [], "skipped": [], "errors": []}
        if not directory.exists():
            return report
        try:
            restrict_dir(directory)
        except Exception:
            pass
        try:
            items = sorted(directory.iterdir())
        except OSError as e:
            report["errors"].append(str(e))
            return report
        for item in items:
            if not item.is_dir() or item.is_symlink():
                continue
            if not re.match(r"^[A-Za-z0-9_\-]{1,64}$", item.name):
                report["skipped"].append(f"{item.name}: bad dirname")
                continue
            manifest = item / "plugin.json"
            init = item / "__init__.py"
            if not manifest.exists() or not init.exists():
                report["skipped"].append(f"{item.name}: missing plugin.json")
                continue
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except Exception as e:
                report["skipped"].append(f"{item.name}: bad manifest ({e})")
                continue
            ok, reason = _valid_manifest(data)
            if not ok:
                report["skipped"].append(f"{item.name}: {reason}")
                continue
            allowed, sig_reason = _apply_signature_policy(data, item.name)
            if not allowed:
                report["skipped"].append(f"{item.name}: {sig_reason}")
                continue
            # Code binding: a signed manifest pins __init__.py bytes, so
            # swapping code post-signing invalidates the load.
            expected_code = data.get("code_sha256", "")
            if expected_code:
                try:
                    actual_code = code_hash_for(item)
                except OSError as e:
                    report["skipped"].append(f"{item.name}: unreadable code ({e})")
                    continue
                if not hmac.compare_digest(str(expected_code), actual_code):
                    logger.warning(f"Rejecting plugin '{item.name}': code hash mismatch")
                    report["skipped"].append(f"{item.name}: code hash mismatch")
                    continue
            if len(self._plugins) >= MAX_PLUGINS:
                report["skipped"].append(f"{item.name}: plugin cap reached")
                continue
            module_name = f"deepans_code.plugins.{item.name}"
            try:
                if module_name in sys.modules:
                    # Never implicitly reload during scan; explicit reload_plugin() only.
                    report["skipped"].append(f"{item.name}: already loaded (use reload_plugin)")
                    continue
                module = importlib.import_module(module_name)
                if hasattr(module, "register"):
                    module.register(self)
                    report["loaded"].append(item.name)
                else:
                    report["skipped"].append(f"{item.name}: no register()")
            except Exception as e:
                logger.error(f"Failed to load plugin from {item}: {e}")
                report["errors"].append(f"{item.name}: {e}")
        return report


plugin_manager = PluginManager()


def _sign_cli(plugin_dir: str) -> int:
    """Sign a plugin's manifest: python -m deepans_code.plugin_manager sign <dir>."""
    manifest = Path(plugin_dir) / "plugin.json"
    if not manifest.exists():
        print(f"No plugin.json in {plugin_dir}")
        return 1
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Bad manifest: {e}")
        return 1
    try:
        data["code_sha256"] = code_hash_for(Path(plugin_dir))
        sig = sign_manifest(data)
    except (ValueError, OSError) as e:
        print(str(e))
        return 1
    data["signature"] = sig
    manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Signed {manifest}")
    return 0


if __name__ == "__main__":
    import sys as _sys

    if len(_sys.argv) == 3 and _sys.argv[1] == "sign":
        raise SystemExit(_sign_cli(_sys.argv[2]))
    print("Usage: python -m deepans_code.plugin_manager sign <plugin_dir>")
    raise SystemExit(2)
