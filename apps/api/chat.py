"""
Chat REST + WebSocket. Streams Agent.send_message_stream() to the browser.

Web tool profile (safety first): run_command and delete_file are DISABLED
on the web — remote code execution from a browser session is exactly the
threat the CLI sandbox was never asked to face. File creation/editing run
inside a per-user sandbox dir, serialized by a global turn lock so the
process-global tools workspace can never cross users.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from deepans_code import tools as tools_mod
from deepans_code.models import get_all_models

from . import ratelimit
from .crypto import verify_jwt
from .deps import client_ip, current_user, require_csrf
from .store import get_web_db

router = APIRouter(tags=["chat"])

WEB_DISABLED_TOOLS = {"run_command", "delete_file"}

# ---------------------------------------------------------------------------
# Web-search detection: patterns that indicate the user wants live web data
# ---------------------------------------------------------------------------
_SEARCH_PATTERNS = re.compile(
    r"(?:^|\s)(?:what(?:'s| is| are) (?:the |a )?(?:latest|current|newest|recent|top|best|most popular)"
    r"|who (?:is|won|invented|created|founded|designed|authored|wrote|directed|starred)"
    r"|when (?:is|was|did|will|does)"
    r"|where (?:is|was|are|can|do|does)"
    r"|how (?:much|many|old|tall|far|long|fast|hot|cold|does|did|would|should|can|could)"
    r"|news|weather|price|stock|score|result|ranking|forecast"
    r"|search|look up|find|google|browse|research)"
    r"|20[2-3]\d"   # year references like 2024, 2025, 2026
    r"|\b(?:latest|current|recent|today|now|right now|this week|this month|this year)\b"
    r"|\b(?:breaking|live|real.?time|up.?to.?date|fresh)\b",
    re.IGNORECASE,
)

# Words that suggest factual/coding questions (NOT web search)
_CODE_PATTERNS = re.compile(
    r"(?:^|\s)(?:write|create|fix|debug|explain|refactor|implement|add|remove|update|change|rename|move|copy|paste"
    r"|how (?:do I|to|does|did|would|should|can|could)"
    r"|what (?:is|are|does|did|would|should|can|could)"
    r"|why (?:is|are|does|did|would|should|can|could)"
    r"|class |def |function |import |module |file|error|bug|test|code|program|script"
    r"|python|javascript|typescript|java\b|c\+\+|rust|go\b|ruby|php|swift|kotlin"
    r"|api |sdk |npm |pip |cargo |docker |git |github|gitlab"
    r"|algorithm|data structure|array|list|dict|map|set|tree|graph"
    r"|syntax|compile|runtime|debug|trace|stack|heap|memory)",
    re.IGNORECASE,
)


def _needs_web_search(message: str) -> bool:
    """Return True if the message likely requires live web data."""
    if not message or len(message.strip()) < 5:
        return False
    msg = message.strip()
    # If explicitly tagged with web search hint from frontend
    if "[Use web search" in msg:
        return True
    # Code-heavy questions don't need web search
    if _CODE_PATTERNS.search(msg) and not _SEARCH_PATTERNS.search(msg):
        return False
    return bool(_SEARCH_PATTERNS.search(msg))


def _extract_search_query(message: str) -> str:
    """Extract a clean search query from the user message."""
    # Strip the frontend tag
    cleaned = re.sub(r"\s*\[.*?Use web search.*?\]\s*", " ", message).strip()
    # Take the first sentence or first 200 chars
    first_sentence = re.split(r"[.!?\n]", cleaned)[0].strip()
    if len(first_sentence) > 200:
        first_sentence = first_sentence[:200]
    return first_sentence or cleaned[:200]


def _do_web_search(query: str) -> str:
    """Execute web search and return formatted results. Timeout after 5s."""
    import concurrent.futures
    try:
        def _run():
            from deepans_code.web_search import search_web
            return search_web(query, max_results=5)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_run)
            results = future.result(timeout=5)
        if not results:
            return ""
        lines = [f"[Live web search results for: {query}]"]
        for i, r in enumerate(results, 1):
            title = r.get("title", "")
            url = r.get("url", "")
            snippet = r.get("snippet", "")
            lines.append(f"{i}. {title}\n   {url}\n   {snippet}")
        return "\n".join(lines)
    except concurrent.futures.TimeoutError:
        logger.warning(f"Pre-search timed out for: {query[:50]}")
        return ""
    except Exception as e:
        logger.warning(f"Pre-search failed: {e}")
        return ""
_WEB_USER_LOCKS = {}
_WEB_USER_LOCKS_LOCK = threading.Lock()
_WEB_CTX = threading.local()  # .active=True only inside a web turn
MAX_UPLOAD_BYTES = 300 * 1024 * 1024
MAX_UPLOAD_BATCH_BYTES = 300 * 1024 * 1024
SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._ -]+")


def _get_user_lock(uid: int) -> threading.Lock:
    with _WEB_USER_LOCKS_LOCK:
        if uid not in _WEB_USER_LOCKS:
            _WEB_USER_LOCKS[uid] = threading.Lock()
        return _WEB_USER_LOCKS[uid]


def web_tools_safe() -> bool:
    return os.environ.get("DEEPANCODE_WEB_SAFE_TOOLS", "1").strip() != "0"


def _web_active() -> bool:
    return bool(getattr(_WEB_CTX, "active", False))


def web_tools_safe() -> bool:
    return os.environ.get("DEEPANCODE_WEB_SAFE_TOOLS", "1").strip() != "0"


def user_sandbox(uid: int) -> str:
    from pathlib import Path

    root = Path.home() / ".deepans-code" / "web_files" / str(int(uid))
    root.mkdir(parents=True, exist_ok=True)
    from deepans_code.permissions import restrict_dir
    restrict_dir(root)
    return str(root)


def _guarded_execute(tool_name, arguments):
    # Thread-local gate: CLI turns (flag unset) are never affected even if a
    # web turn holds the lock concurrently.
    if web_tools_safe() and _web_active() and tool_name in WEB_DISABLED_TOOLS:
        return f"Error: Tool '{tool_name}' is disabled in the web profile"
    return _ORIG_EXECUTE(tool_name, arguments)


def _guarded_parallel(tool_calls):
    if web_tools_safe() and _web_active():
        kept = []
        dropped = {}
        for tc in tool_calls or []:
            name = (tc.get("function", {}) or {}).get("name", "") if isinstance(tc, dict) else ""
            if name in WEB_DISABLED_TOOLS:
                dropped[tc.get("id", "")] = f"Error: Tool '{name}' is disabled in the web profile"
            else:
                kept.append(tc)
        out = _ORIG_PARALLEL(kept)
        for cid, msg in dropped.items():
            out.append((cid, msg))
        return out
    return _ORIG_PARALLEL(tool_calls)


_ORIG_EXECUTE = tools_mod.execute_tool
_ORIG_PARALLEL = tools_mod.execute_tools_parallel
_ORIG_SCHEMAS = tools_mod.get_tool_schemas


def run_guarded_turn(uid: int, conversation_id: int, message: str):
    """Generator: holds the per-user turn lock, sandboxes workspace+tools, streams events."""
    from deepans_code import agent as agent_mod
    from deepans_code.agent import Agent
    from deepans_code.config import config_mgr
    from .store import get_web_db

    previous_workspace = tools_mod.workspace.workspace
    previous_agent_db = agent_mod.db
    user_lock = _get_user_lock(uid)
    user_lock.acquire()
    old_exec, old_par = tools_mod.execute_tool, tools_mod.execute_tools_parallel
    old_schemas, old_agent_schemas = tools_mod.get_tool_schemas, agent_mod.get_tool_schemas
    runtime_provider = ""
    if web_tools_safe():
        def _filtered_schemas():
            if not _web_active():
                return _ORIG_SCHEMAS()  # concurrent CLI turn: untouched
            return [s for s in _ORIG_SCHEMAS()
                    if ((s.get("function", {}) or {}).get("name", "")) not in WEB_DISABLED_TOOLS]
        tools_mod.get_tool_schemas = _filtered_schemas
        agent_mod.get_tool_schemas = _filtered_schemas
    _WEB_CTX.active = True
    try:
        # Web conversation IDs belong to the web database, not the CLI database.
        # Bind Agent persistence to the same database for this isolated turn.
        agent_mod.db = get_web_db()
        user_key = get_web_db().get_user_key(uid, config_mgr.get("provider", "openrouter"))
        if user_key:
            from deepans_code.security import APIKeyEncryption
            runtime_provider = config_mgr.get("provider", "openrouter")
            encryption = APIKeyEncryption()
            plaintext_key = encryption.decrypt(user_key)
            if user_key.startswith("enc:"):
                get_web_db().set_user_key(uid, runtime_provider, encryption.encrypt(plaintext_key))
            config_mgr.set_runtime_api_key(runtime_provider, plaintext_key)
        tools_mod.workspace.set_workspace(user_sandbox(uid))
        tools_mod.execute_tool = _guarded_execute
        tools_mod.execute_tools_parallel = _guarded_parallel
        agent = Agent(conversation_id=conversation_id, database=get_web_db())
        # --- Pre-search: inject live web results so the LLM always has data ---
        enriched_message = message
        if _needs_web_search(message):
            search_query = _extract_search_query(message)
            search_results = _do_web_search(search_query)
            if search_results:
                enriched_message = (
                    f"{message}\n\n"
                    f"---\n"
                    f"IMPORTANT: The following are LIVE WEB SEARCH RESULTS. "
                    f"Use them to answer the user's question accurately. "
                    f"Cite sources by title and URL when relevant.\n\n"
                    f"{search_results}\n"
                    f"---"
                )
        for step in agent.send_message_stream(enriched_message):
            yield step
    finally:
        if runtime_provider:
            config_mgr.clear_runtime_api_key(runtime_provider)
        _WEB_CTX.active = False
        tools_mod.execute_tool = old_exec
        tools_mod.execute_tools_parallel = old_par
        tools_mod.get_tool_schemas = old_schemas
        agent_mod.get_tool_schemas = old_agent_schemas
        agent_mod.db = previous_agent_db
        try:
            tools_mod.workspace.workspace = previous_workspace
        except Exception:
            pass
        user_lock.release()


# -- REST ---------------------------------------------------------------------
class ConvIn(BaseModel):
    title: str = Field(default="Untitled", max_length=200)


class RenameIn(BaseModel):
    title: str = Field(max_length=200)


def _safe_upload_name(name: str) -> str:
    clean = SAFE_FILENAME.sub("_", Path(name or "upload").name).strip(" .")
    return (clean or "upload")[:160]


@router.post("/api/uploads")
async def upload_files(request: Request, files: list[UploadFile] = File(...),
                       user: dict = Depends(current_user)):
    """Store browser uploads in the authenticated user's private web workspace."""
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")
    upload_dir = Path(user_sandbox(user["id"])) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    results = []
    total_size = 0
    try:
        for upload in files:
            name = _safe_upload_name(upload.filename)
            target = upload_dir / (uuid.uuid4().hex + "-" + name)
            size = 0
            try:
                with target.open("wb") as output:
                    while True:
                        chunk = await upload.read(1024 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        total_size += len(chunk)
                        if size > MAX_UPLOAD_BYTES:
                            raise HTTPException(status_code=413, detail=f"{name} exceeds the 300 MB per-file limit")
                        if total_size > MAX_UPLOAD_BATCH_BYTES:
                            raise HTTPException(status_code=413, detail="The combined upload exceeds the 300 MB batch limit")
                        output.write(chunk)
            except Exception:
                target.unlink(missing_ok=True)
                raise
            results.append({"id": target.name, "name": name, "size": size,
                            "content_type": upload.content_type or "application/octet-stream"})
            await upload.close()
    except HTTPException:
        for result in results:
            (upload_dir / result["id"]).unlink(missing_ok=True)
        raise
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}")
    return {"files": results}


@router.get("/api/models")
def list_models(request: Request, user: dict = Depends(current_user)):
    if not ratelimit.check("api", f"models:{user['id']}"):
        raise HTTPException(status_code=429, detail="Rate limited")
    return {"models": get_all_models()}


@router.get("/api/providers")
def list_providers(request: Request, user: dict = Depends(current_user)):
    """Return all providers with their metadata for the frontend."""
    from deepans_code.models import PROVIDERS
    db = get_web_db()
    providers = {}
    for prov_key, prov_data in PROVIDERS.items():
        key_env = prov_data.get("key_env")
        has_key = bool(
            (os.environ.get(key_env, "") if key_env else "")
            or (not user.get("service") and db.get_user_key(user["id"], prov_key))
        )
        providers[prov_key] = {
            "id": prov_key,
            "name": prov_data.get("name", prov_key),
            "url": prov_data.get("url", ""),
            "description": prov_data.get("description", ""),
            "free_tier": prov_data.get("free_tier", False),
            "key_env": key_env,
            "has_key": has_key,
            "model_count": len(prov_data.get("models", [])),
        }
    return {"providers": providers}


@router.get("/api/conversations")
def list_conversations(request: Request, user: dict = Depends(current_user),
                       search: str = Query(default="", max_length=200),
                       limit: int = Query(default=50, ge=1, le=200)):
    db = get_web_db()
    if user.get("service"):
        raise HTTPException(status_code=403, detail="User endpoint")
    return {"conversations": db.get_user_conversations(user["id"], limit, search)}


@router.post("/api/conversations")
async def create_conversation(body: ConvIn, request: Request, user: dict = Depends(current_user)):
    from deepans_code.config import config_mgr
    cid = get_web_db().create_conversation_for_user(
        user["id"], body.title or "Untitled",
        config_mgr.get("model", ""), config_mgr.get("provider", ""), config_mgr.get("mode", "code"))
    return {"conversation_id": cid}


@router.get("/api/conversations/{cid}")
def get_conversation(cid: int, request: Request, user: dict = Depends(current_user)):
    conv = get_web_db().get_user_conversation(user["id"], cid)
    if not conv:
        raise HTTPException(status_code=404, detail="Not found")
    return conv


@router.get("/api/conversations/{cid}/messages")
def get_messages(cid: int, request: Request, user: dict = Depends(current_user),
                 limit: int = Query(default=500, ge=1, le=1000)):
    db = get_web_db()
    if not db.get_user_conversation(user["id"], cid):
        raise HTTPException(status_code=404, detail="Not found")
    return {"messages": db.get_messages(cid, limit)}


@router.patch("/api/conversations/{cid}")
async def rename_conversation(cid: int, body: RenameIn, request: Request,
                              user: dict = Depends(current_user)):
    ok = get_web_db().rename_user_conversation(user["id"], cid, body.title)
    if not ok:
        raise HTTPException(status_code=404, detail="Not found")
    return {"status": "renamed"}


@router.delete("/api/conversations/{cid}")
def delete_conversation(cid: int, request: Request, user: dict = Depends(current_user)):
    ok = get_web_db().delete_user_conversation(user["id"], cid)
    if not ok:
        raise HTTPException(status_code=404, detail="Not found")
    return {"status": "deleted"}


@router.get("/api/settings")
def get_settings(request: Request, user: dict = Depends(current_user)):
    from deepans_code.config import config_mgr
    from deepans_code.models import PROVIDERS
    db = get_web_db()
    keys = {}
    for prov, provider_data in PROVIDERS.items():
        key_env = provider_data.get("key_env")
        keys[prov] = bool(
            (os.environ.get(key_env, "") if key_env else "")
            or db.get_user_key(user["id"], prov))
    mode = config_mgr.get("mode", "agent")
    if mode == "code" and config_mgr.get("agent", "build") == "build":
        mode = "agent"
        config_mgr.set("mode", "agent")
        config_mgr.set("agent", "agent")
    theme = config_mgr.get("theme", "dark")
    valid_themes = {"dark", "light", "midnight", "ocean", "aurora", "rose", "forest", "sunset", "graphite", "copper", "lavender", "mint", "ruby", "amber", "indigo", "slate", "cyber", "plum", "sand", "coral", "jade", "ice", "solar", "mono"}
    if theme not in valid_themes:
        theme = "dark"
    return {
        "model": config_mgr.get("model", ""),
        "provider": config_mgr.get("provider", ""),
        "mode": mode,
        "effort": config_mgr.get("effort", "medium"),
        "thinking": config_mgr.get("thinking", True),
        "theme": theme,
        "keys_configured": keys,
    }


class SettingsIn(BaseModel):
    model: str | None = Field(default=None, max_length=200)
    provider: str | None = Field(default=None, max_length=64)
    mode: str | None = Field(default=None, max_length=32)
    effort: str | None = Field(default=None, max_length=32)
    thinking: bool | None = None
    theme: str | None = Field(default=None, max_length=32)


@router.patch("/api/settings")
async def patch_settings(body: SettingsIn, request: Request, user: dict = Depends(current_user)):
    from deepans_code.config import config_mgr
    allowed = {"model", "provider", "mode", "effort", "thinking", "theme"}
    data = body.model_dump(exclude_none=True)
    if "theme" in data and data["theme"] not in {"dark", "light", "midnight", "ocean", "aurora", "rose", "forest", "sunset", "graphite", "copper", "lavender", "mint", "ruby", "amber", "indigo", "slate", "cyber", "plum", "sand", "coral", "jade", "ice", "solar", "mono"}:
        raise HTTPException(status_code=400, detail="Unsupported theme")
    if "mode" in data and data["mode"] not in {"plan", "agent", "code", "architect", "ask", "debug", "review"}:
        raise HTTPException(status_code=400, detail="Unsupported mode")
    for key, value in data.items():
        if key in allowed:
            config_mgr.set(key, value)
    return {"status": "updated"}


class KeyIn(BaseModel):
    provider: str = Field(max_length=64)
    api_key: str = Field(max_length=512)


@router.post("/api/keys")
async def save_key(body: KeyIn, request: Request, user: dict = Depends(current_user)):
    """Store a provider key encrypted (AES-at-rest)."""
    from deepans_code.models import PROVIDERS
    provider = body.provider.strip().lower()
    api_key = body.api_key.strip().strip("\"'")
    if not api_key:
        raise HTTPException(status_code=400, detail="API key is required")
    if provider not in PROVIDERS or not PROVIDERS[provider].get("key_env"):
        raise HTTPException(status_code=400, detail="Unknown provider")
    from deepans_code.security import APIKeyEncryption
    try:
        enc = APIKeyEncryption().encrypt(api_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Encryption unavailable: {e}")
    get_web_db().set_user_key(user["id"], provider, enc)
    get_web_db().audit("key_saved", user["id"], client_ip(request), provider)
    return {"status": "saved"}


@router.get("/api/usage")
def usage(request: Request, user: dict = Depends(current_user)):
    db = get_web_db()
    convs = db.get_user_conversations(user["id"], 1000)
    return {
        "conversations": len(convs),
        "total_tokens": sum(c.get("total_tokens", 0) or 0 for c in convs),
        "total_messages": sum(c.get("message_count", 0) or 0 for c in convs),
    }


@router.get("/api/health")
def health():
    from deepans_code import __version__
    return {"status": "healthy", "version": __version__}


@router.get("/api/status")
def status(request: Request, user: dict = Depends(current_user)):
    from deepans_code.config import config_mgr
    return {
        "model": config_mgr.get("model", ""),
        "provider": config_mgr.get("provider", ""),
        "mode": config_mgr.get("mode", "code"),
    }


# -- WebSocket ------------------------------------------------------------------
async def _ws_authed(websocket: WebSocket) -> dict | None:
    """No auth required — return default user."""
    return {"id": 1, "email": "user@deepancode.local", "jti": "default", "service": False}


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    await websocket.accept()
    user = await _ws_authed(websocket)
    if not user:
        await websocket.send_json({"type": "error", "message": "Unauthorized"})
        await websocket.close(code=4401)
        return
    await websocket.send_json({"type": "auth_ok"})
    db = get_web_db()
    try:
        while True:
            try:
                raw = await websocket.receive_text()
            except WebSocketDisconnect:
                break
            if len(raw.encode("utf-8", "ignore")) > 32768:
                await websocket.send_json({"type": "error", "message": "Message too large"})
                continue
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            if data.get("type") != "chat":
                continue
            if not ratelimit.check("chat", f"chat:{user['id']}"):
                await websocket.send_json({"type": "error", "message": "Rate limited"})
                continue
            message = str(data.get("message", ""))[:32768]
            attachments = data.get("attachments") or []
            if isinstance(attachments, list):
                attachment_lines = []
                upload_root = Path(user_sandbox(user["id"])) / "uploads"
                for item in attachments[:20]:
                    if not isinstance(item, dict):
                        continue
                    file_id = Path(str(item.get("id", ""))).name
                    stored = upload_root / file_id
                    if stored.is_file() and upload_root in stored.parents:
                        attachment_lines.append(f"- {item.get('name', file_id)}: uploads/{file_id}")
                if attachment_lines:
                    message += "\n\nUploaded files available in the workspace:\n" + "\n".join(attachment_lines)
            raw_cid = data.get("conversation_id")
            try:
                cid = int(raw_cid) if raw_cid is not None else 0
            except (ValueError, TypeError):
                await websocket.send_json({"type": "error", "message": "Invalid conversation_id"})
                continue
            if not message.strip():
                await websocket.send_json({"type": "error", "message": "message is required"})
                continue
            if cid:
                if not db.get_user_conversation(user["id"], cid):
                    await websocket.send_json({"type": "error", "message": "Not found"})
                    continue
                conv_id = cid
            else:
                from deepans_code.config import config_mgr
                conv_id = db.create_conversation_for_user(
                    user["id"], (message[:60] or "Untitled"),
                    config_mgr.get("model", ""), config_mgr.get("provider", ""),
                    config_mgr.get("mode", "code"))
            loop = asyncio.get_event_loop()
            aq = asyncio.Queue()
            def _run():
                try:
                    for step in run_guarded_turn(user["id"], conv_id, message):
                        loop.call_soon_threadsafe(aq.put_nowait, step)
                except Exception as e:
                    loop.call_soon_threadsafe(aq.put_nowait, ("error", f"Agent failed: {str(e)[:200]}"))
                finally:
                    loop.call_soon_threadsafe(aq.put_nowait, None)
            t = threading.Thread(target=_run, daemon=True)
            t.start()
            try:
                while True:
                    item = await aq.get()
                    if item is None:
                        break
                    step_type, content = item
                    await websocket.send_json({"type": step_type, "message": content})
            except Exception as e:
                await websocket.send_json({"type": "error", "message": f"Stream error: {str(e)[:200]}"})
            await websocket.send_json({"type": "done", "conversation_id": conv_id})
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass
