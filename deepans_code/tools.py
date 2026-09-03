"""
Tools module for DeepanCode.
Defines available tools for the AI agent and handles their execution.
Includes command sandboxing, workspace boundary, logging, and web search.
Now with improved tool execution, validation, and result formatting.
"""

import os
import json
import shlex
import subprocess
import platform
import logging
import httpx
import tempfile
import time
from typing import Dict, Any, List, Tuple
from pathlib import Path

from deepans_code.security import CommandSandbox, WorkspaceBoundary

logger = logging.getLogger("deepans_code.tools")

sandbox = CommandSandbox()
workspace = WorkspaceBoundary()

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file at the given path",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to read"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": "Create a new file with the given content",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path where the file should be created"},
                    "content": {"type": "string", "description": "Content to write to the file"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Edit an existing file by replacing old text with new text",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to edit"},
                    "old_text": {"type": "string", "description": "Text to find and replace"},
                    "new_text": {"type": "string", "description": "Text to replace with"},
                    "replace_all": {"type": "boolean", "description": "Replace all occurrences (default false; ambiguous matches are rejected without this)"}
                },
                "required": ["path", "old_text", "new_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a shell command and return the output",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List contents of a directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the directory to list"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a file at the given path",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to delete"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web using DuckDuckGo. Returns titles, URLs, and snippets. Use for finding current information, documentation, code examples, or any real-time data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query string"},
                    "max_results": {"type": "integer", "description": "Maximum results to return (default 5)"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch and extract text content from a URL. Use to read documentation, tutorials, or any web page content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full URL to fetch (must start with http:// or https://)"},
                    "max_length": {"type": "integer", "description": "Maximum characters to return (default 5000)"}
                },
                "required": ["url"]
            }
        }
    }
]


def set_workspace(path: str):
    workspace.set_workspace(path)
    logger.info(f"Workspace set to: {path}")


def get_tool_schemas():
    return TOOL_SCHEMAS


MAX_TOOL_OUTPUT_CHARS = 20000
MAX_FILE_WRITE_BYTES = 1_000_000  # 1 MB per create/edit to prevent disk-fill DoS

def execute_tool(tool_name, arguments):
    start = time.time()
    success = True
    try:
        if not isinstance(arguments, dict):
            return f"Error: Invalid arguments for '{tool_name}' (must be an object)"
        if tool_name == "read_file":
            result = _read_file(arguments.get("path", ""))
        elif tool_name == "create_file":
            result = _create_file(arguments.get("path", ""), arguments.get("content", ""))
        elif tool_name == "edit_file":
            result = _edit_file(
                arguments.get("path", ""), arguments.get("old_text", ""),
                arguments.get("new_text", ""),
                replace_all=bool(arguments.get("replace_all", False)),
            )
        elif tool_name == "run_command":
            result = _run_command(arguments.get("command", ""))
        elif tool_name == "list_dir":
            result = _list_dir(arguments.get("path", ""))
        elif tool_name == "delete_file":
            result = _delete_file(arguments.get("path", ""))
        elif tool_name == "web_search":
            result = _web_search(arguments.get("query", ""), arguments.get("max_results", 5))
        elif tool_name == "web_fetch":
            result = _web_fetch(arguments.get("url", ""), arguments.get("max_length", 5000))
        else:
            result = f"Error: Unknown tool '{tool_name}'"
            success = False
    except (OSError, ValueError, TypeError, RuntimeError, AttributeError) as e:
        logger.error(f"Tool execution error ({tool_name}): {e}")
        result = f"Error executing {tool_name}: {str(e)}"
        success = False
    except Exception as e:  # network errors (httpx.*), provider errors, etc.
        logger.error(f"Tool execution error ({tool_name}): {type(e).__name__}: {e}")
        result = f"Error executing {tool_name}: {type(e).__name__}: {str(e)[:300]}"
        success = False
    if isinstance(result, str) and len(result) > MAX_TOOL_OUTPUT_CHARS:
        result = result[:MAX_TOOL_OUTPUT_CHARS] + f"\n\n... (truncated {len(result) - MAX_TOOL_OUTPUT_CHARS} chars)"

    latency = time.time() - start
    try:
        import deepans_code.metrics as _m
        _m.metrics.record_tool_call(tool_name, latency, success)
    except (ImportError, AttributeError, RuntimeError):
        pass

    return result


def execute_tools_parallel(tool_calls: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """Execute multiple tool calls in parallel using thread pool."""
    import concurrent.futures
    results = []
    futures = []

    import uuid
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        for i, tc in enumerate(tool_calls):
            if isinstance(tc, dict) and "function" in tc:
                fn_name = tc["function"].get("name", "")
                fn_args_str = tc["function"].get("arguments", "{}")
                call_id = tc.get("id", "") or f"call_parallel_{i}_{uuid.uuid4().hex[:8]}"
                try:
                    fn_args = json.loads(fn_args_str) if isinstance(fn_args_str, str) else fn_args_str
                    if not isinstance(fn_args, dict):
                        logger.warning(f"Parallel tool '{fn_name}' args not a dict; skipping")
                        results.append((call_id, f"Error: Tool '{fn_name}' args must be an object"))
                        continue
                except (json.JSONDecodeError, ValueError, TypeError) as e:
                    logger.warning(f"Parallel tool '{fn_name}' bad JSON args, skipping: {e}")
                    results.append((call_id, f"Error: Tool '{fn_name}' has invalid arguments"))
                    continue
                futures.append((call_id, fn_name, executor.submit(execute_tool, fn_name, fn_args)))

        for call_id, fn_name, future in futures:
            try:
                result = future.result(timeout=60)
                results.append((call_id, result))
            except concurrent.futures.TimeoutError:
                results.append((call_id, f"Error: Tool '{fn_name}' timed out after 60s"))
            except Exception as e:
                results.append((call_id, f"Error executing {fn_name}: {str(e)}"))

    return results


def _validate_file_path(path: str) -> tuple:
    if not isinstance(path, str):
        return False, "", "Path must be a string"
    is_valid, resolved, reason = workspace.validate_path(path)
    if not is_valid:
        logger.warning(f"Path validation failed: {reason}")
    return is_valid, resolved, reason


def _read_file(path):
    is_valid, resolved, reason = _validate_file_path(path)
    if not is_valid:
        return f"Error: {reason}"
    p = Path(resolved)
    if not p.exists():
        return f"Error: File not found: {p}"
    if not p.is_file():
        return f"Error: Not a file: {p}"
    try:
        if p.stat().st_size > 5_000_000:  # 5MB guard before materializing
            return f"Error: File too large (>5MB): {p}"
        content = p.read_text(encoding="utf-8")
        lines = content.split("\n")
        if len(lines) > 500:
            return "\n".join(lines[:500]) + f"\n\n... ({len(lines) - 500} more lines truncated)"
        return content
    except UnicodeDecodeError:
        return f"Error: Cannot read binary file: {p}"


def _create_file(path, content):
    is_valid, resolved, reason = _validate_file_path(path)
    if not is_valid:
        return f"Error: {reason}"
    if content is None:
        content = ""
    if not isinstance(content, str):
        return "Error: content must be a string"
    if len(content.encode("utf-8", errors="ignore")) > MAX_FILE_WRITE_BYTES:
        return f"Error: content too large (max {MAX_FILE_WRITE_BYTES} bytes)"
    p = Path(resolved)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: temp file + os.replace so partial writes never
        # leave a corrupt file behind.
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, p)
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass
        logger.info(f"File created: {p}")
        return f"Successfully created: {p}"
    except (OSError, UnicodeEncodeError) as e:
        return f"Error creating file: {str(e)}"


def _edit_file(path, old_text, new_text, replace_all: bool = False):
    is_valid, resolved, reason = _validate_file_path(path)
    if not is_valid:
        return f"Error: {reason}"
    p = Path(resolved)
    if not p.exists():
        return f"Error: File not found: {p.name}"
    if not old_text:
        return "Error: old_text must not be empty"
    if len(new_text.encode("utf-8", errors="ignore")) > MAX_FILE_WRITE_BYTES:
        return f"Error: new_text too large (max {MAX_FILE_WRITE_BYTES} bytes)"
    try:
        if p.stat().st_size > 5 * MAX_FILE_WRITE_BYTES:
            return "Error: file too large to edit safely"
        content = p.read_text(encoding="utf-8")
        occurrences = content.count(old_text)
        if occurrences == 0:
            return f"Error: Text not found in file: {old_text[:50]}..."
        if occurrences > 1 and not replace_all:
            return (
                f"Error: Ambiguous edit — text occurs {occurrences} times. "
                "Provide more surrounding context to make it unique, "
                "or call with replace_all=True."
            )
        if replace_all:
            new_content = content.replace(old_text, new_text)
        else:
            new_content = content.replace(old_text, new_text, 1)
        # Atomic write via temp file + os.replace; keep a .bak backup.
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(new_content)
            backup = p.with_suffix(p.suffix + ".bak")
            try:
                import shutil
                shutil.copy2(p, backup)
            except OSError:
                pass
            os.replace(tmp_path, p)
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass
        logger.info(f"File edited: {p} (occurrences={occurrences})")
        return f"Successfully edited: {p}"
    except (OSError, UnicodeDecodeError) as e:
        return f"Error editing file: {str(e)}"


def _run_command(command):
    if not command:
        return "Error: Empty command"
    is_safe, reason = sandbox.validate_command(command)
    if not is_safe:
        logger.warning(f"Command blocked: {reason}")
        return f"Error: Command blocked by security policy - {reason}"
    command = sandbox.sanitize_command(command)
    # Re-validate after sanitization (sanitizer may strip characters).
    is_safe, reason = sandbox.validate_command(command)
    if not is_safe:
        logger.warning(f"Command blocked after sanitize: {reason}")
        return f"Error: Command blocked by security policy - {reason}"
    try:
        # User must never invoke shells directly — they are denied even
        # though we use one internally on Windows for builtins (echo/dir/…).
        lowered = command.strip().lower()
        if lowered.startswith(("powershell", "pwsh", "cmd")):
            return "Error: Command blocked by security policy - powershell/cmd execution is denied"
        try:
            cwd = str(workspace.workspace)
        except Exception:
            cwd = None
        is_windows = platform.system() == "Windows"
        if is_windows:
            # Validated single command only (no metachars per sandbox), run
            # via constrained powershell so builtins like echo/dir work.
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True, text=True, timeout=60, cwd=cwd,
            )
        else:
            try:
                argv = shlex.split(command, posix=True)
            except ValueError as e:
                return f"Error: Unparseable command: {e}"
            if not argv:
                return "Error: Empty command"
            result = subprocess.run(argv, shell=False, capture_output=True, text=True, timeout=60, cwd=cwd)
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += f"\n[STDERR] {result.stderr}" if output else result.stderr
        if result.returncode != 0:
            output += f"\n[Exit Code: {result.returncode}]"
        logger.debug(f"Command executed: {command[:80]}")
        return output.strip() if output else "Command executed successfully (no output)"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 60 seconds"
    except Exception as e:
        return f"Error running command: {str(e)}"


def _list_dir(path):
    is_valid, resolved, reason = _validate_file_path(path)
    if not is_valid:
        return f"Error: {reason}"
    p = Path(resolved)
    if not p.exists():
        return f"Error: Directory not found: {p}"
    if not p.is_dir():
        return f"Error: Not a directory: {p}"
    try:
        entries = []
        for item in sorted(p.iterdir())[:200]:
            if item.is_dir():
                entries.append(f"  [DIR]  {item.name}/")
            else:
                try:
                    size = item.stat().st_size
                except OSError:
                    size = -1
                entries.append(f"  [FILE] {item.name} ({size} bytes)")
        # Show relative name only — never leak absolute workspace paths to the LLM.
        display = p.name or str(p)
        return f"Contents of {display}:\n" + "\n".join(entries) if entries else f"Directory is empty: {display}"
    except Exception as e:
        return f"Error listing directory: {str(e)}"


def _delete_file(path):
    is_valid, resolved, reason = _validate_file_path(path)
    if not is_valid:
        return f"Error: {reason}"
    p = Path(resolved)
    if not p.exists():
        return f"Error: File not found: {p}"
    try:
        if p.is_file():
            p.unlink()
            logger.info(f"File deleted: {p}")
            return f"Successfully deleted: {p}"
        else:
            return "Error: Not a file (directory deletion is not supported)"
    except OSError as e:
        return f"Error deleting file: {str(e)}"


def _web_search(query, max_results=5):
    if not query:
        return "Error: Empty search query"
    try:
        from deepans_code.web_search import search_web
        results = search_web(query, max_results=max_results)
        if not results:
            return f"No results found for: {query}"
        output = [f"Search results for: {query}\n"]
        for i, r in enumerate(results, 1):
            title = r.get("title", "No title")
            url = r.get("url", "")
            snippet = r.get("snippet", "")
            output.append(f"{i}. {title}\n   URL: {url}\n   {snippet}\n")
        return "\n".join(output)
    except ImportError:
        return "Error: Web search module not available."
    except Exception as e:
        logger.error(f"Web search error: {e}")
        return f"Error searching web: {str(e)}"


def _web_fetch(url, max_length=5000):
    if not url:
        return "Error: Empty URL"
    if not url.startswith(("http://", "https://")):
        return "Error: URL must start with http:// or https://"
    try:
        from deepans_code.web_search import fetch_url_content, is_safe_fetch_url
        ok, reason = is_safe_fetch_url(url)
        if not ok:
            return f"Error: Blocked URL ({reason})"
        return fetch_url_content(url, max_length=max_length)
    except ImportError:
        try:
            from deepans_code.web_search import is_safe_fetch_url as _gate
            ok, reason = _gate(url)
            if not ok:
                return f"Error: Blocked URL ({reason})"
            with httpx.Client(timeout=15, follow_redirects=False) as client:
                response = client.get(url, headers={"User-Agent": "DeepanCode/3.0"})
                response.raise_for_status()
                content = response.text
                import re
                content = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL)
                content = re.sub(r'<style[^>]*>.*?</style>', '', content, flags=re.DOTALL)
                content = re.sub(r'<[^>]+>', ' ', content)
                content = re.sub(r'\s+', ' ', content).strip()
                if len(content) > max_length:
                    content = content[:max_length] + "\n\n... (truncated)"
                return content
        except Exception as e:
            return f"Error fetching URL: {str(e)}"
