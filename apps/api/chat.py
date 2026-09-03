"""
Chat REST + WebSocket. Streams Agent.send_message_stream() to the browser.

Web tool profile (safety first): run_command and delete_file are DISABLED
on the web — remote code execution from a browser session is exactly the
threat the CLI sandbox was never asked to face. File creation/editing run
inside a per-user sandbox dir, serialized by a global turn lock so the
process-global tools workspace can never cross users.
"""

import asyncio
import json
import os
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from deepans_code import tools as tools_mod
from deepans_code.models import get_all_models

from . import ratelimit
from .crypto import verify_jwt
from .deps import client_ip, current_user, require_csrf
from .store import get_web_db

router = APIRouter(tags=["chat"])

WEB_DISABLED_TOOLS = {"run_command", "delete_file"}
WEB_TURN_LOCK = threading.Lock()
_WEB_CTX = threading.local()  # .active=True only inside a web turn


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
    """Generator: holds the turn lock, sandboxes workspace+tools, streams events."""
    from deepans_code import agent as agent_mod
    from deepans_code.agent import Agent

    previous_workspace = tools_mod.workspace.workspace
    WEB_TURN_LOCK.acquire()
    old_exec, old_par = tools_mod.execute_tool, tools_mod.execute_tools_parallel
    old_schemas, old_agent_schemas = tools_mod.get_tool_schemas, agent_mod.get_tool_schemas
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
        tools_mod.workspace.set_workspace(user_sandbox(uid))
        tools_mod.execute_tool = _guarded_execute
        tools_mod.execute_tools_parallel = _guarded_parallel
        agent = Agent(conversation_id=conversation_id)
        for step in agent.send_message_stream(message):
            yield step
    finally:
        _WEB_CTX.active = False
        tools_mod.execute_tool = old_exec
        tools_mod.execute_tools_parallel = old_par
        tools_mod.get_tool_schemas = old_schemas
        agent_mod.get_tool_schemas = old_agent_schemas
        try:
            tools_mod.workspace.workspace = previous_workspace
        except Exception:
            pass
        WEB_TURN_LOCK.release()


# -- REST ---------------------------------------------------------------------
class ConvIn(BaseModel):
    title: str = Field(default="Untitled", max_length=200)


class RenameIn(BaseModel):
    title: str = Field(max_length=200)


@router.get("/api/models")
def list_models(request: Request, user: dict = Depends(current_user)):
    if not ratelimit.check("api", f"models:{user['id']}"):
        raise HTTPException(status_code=429, detail="Rate limited")
    return {"models": get_all_models()}


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
    require_csrf(request, user)
    if user.get("service"):
        raise HTTPException(status_code=403, detail="User endpoint")
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
    require_csrf(request, user)
    ok = get_web_db().rename_user_conversation(user["id"], cid, body.title)
    if not ok:
        raise HTTPException(status_code=404, detail="Not found")
    return {"status": "renamed"}


@router.delete("/api/conversations/{cid}")
def delete_conversation(cid: int, request: Request, user: dict = Depends(current_user)):
    require_csrf(request, user)
    ok = get_web_db().delete_user_conversation(user["id"], cid)
    if not ok:
        raise HTTPException(status_code=404, detail="Not found")
    return {"status": "deleted"}


@router.get("/api/settings")
def get_settings(request: Request, user: dict = Depends(current_user)):
    from deepans_code.config import config_mgr
    db = get_web_db()
    keys = {}
    if not user.get("service"):
        for prov in ("openrouter", "opencode"):
            keys[prov] = bool(
                os.environ.get("OPENROUTER_API_KEY" if prov == "openrouter" else "OPENCODE_API_KEY")
                or db.get_user_key(user["id"], prov))
    return {
        "model": config_mgr.get("model", ""),
        "provider": config_mgr.get("provider", ""),
        "mode": config_mgr.get("mode", "code"),
        "effort": config_mgr.get("effort", "medium"),
        "thinking": config_mgr.get("thinking", True),
        "theme": config_mgr.get("theme", "dark"),
        "keys_configured": keys,
        "totp_enabled": bool(not user.get("service") and (db.get_user(user["id"]) or {}).get("totp_enabled")),
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
    require_csrf(request, user)
    from deepans_code.config import config_mgr
    allowed = {"model", "provider", "mode", "effort", "thinking", "theme"}
    data = body.model_dump(exclude_none=True)
    for key, value in data.items():
        if key in allowed:
            config_mgr.set(key, value)
    return {"status": "updated"}


class KeyIn(BaseModel):
    provider: str = Field(max_length=64)
    api_key: str = Field(max_length=512)


@router.post("/api/keys")
async def save_key(body: KeyIn, request: Request, user: dict = Depends(current_user)):
    """Store a provider key encrypted (AES-at-rest). Runtime turns use
    service keys in v1; saved keys activate with per-user BYOK plumbing."""
    require_csrf(request, user)
    if user.get("service"):
        raise HTTPException(status_code=403, detail="User endpoint")
    if body.provider.lower() not in ("openrouter", "opencode"):
        raise HTTPException(status_code=400, detail="Unknown provider")
    from deepans_code.security import APIKeyEncryption
    try:
        enc = APIKeyEncryption().encrypt(body.api_key.strip())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Encryption unavailable: {e}")
    get_web_db().set_user_key(user["id"], body.provider, enc)
    get_web_db().audit("key_saved", user["id"], client_ip(request), body.provider)
    return {"status": "saved"}


@router.get("/api/usage")
def usage(request: Request, user: dict = Depends(current_user)):
    db = get_web_db()
    if user.get("service"):
        raise HTTPException(status_code=403, detail="User endpoint")
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
    """First-message auth: {"type":"auth"} (+ optional token).

    Browsers cannot read the HttpOnly session cookie from JS, but they DO
    send it automatically on the WS handshake — so an empty token falls
    back to the cookie. Native clients send the access JWT as token.
    Service token also accepted as token.
    """
    import hmac as _hmac

    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=15)
    except Exception:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("type") != "auth":
        return None
    token = data.get("token", "") or websocket.cookies.get("dc_access", "")
    claims = verify_jwt(token or "", "access")
    if claims:
        user = get_web_db().get_user(int(claims["sub"]))
        if user:
            return {"id": user["id"], "email": user["email"], "jti": claims["jti"]}
    expected = os.environ.get("DEEPANCODE_API_TOKEN", "")
    if expected and token and _hmac.compare_digest(str(token), expected):
        return {"id": 0, "email": "service", "jti": "service", "service": True}
    return None


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    await websocket.accept()
    user = await _ws_authed(websocket)
    if not user:
        await websocket.send_json({"type": "error", "message": "Unauthorized"})
        await websocket.close(code=4401)
        return
    if not ratelimit.check("ws", f"ws:{user['id']}"):
        await websocket.send_json({"type": "error", "message": "Rate limited"})
        await websocket.close(code=4429)
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
            raw_cid = data.get("conversation_id")
            try:
                cid = int(raw_cid) if raw_cid is not None else 0
            except (ValueError, TypeError):
                await websocket.send_json({"type": "error", "message": "Invalid conversation_id"})
                continue
            if not message.strip():
                await websocket.send_json({"type": "error", "message": "message is required"})
                continue
            if user.get("service"):
                conv_id = cid or db.create_conversation(title=message[:60])
            else:
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
            try:
                steps = await loop.run_in_executor(
                    None, lambda: list(run_guarded_turn(user["id"], conv_id, message)))
            except Exception as e:
                await websocket.send_json({"type": "error", "message": f"Agent failed: {str(e)[:200]}"})
                continue
            for step_type, content in steps:
                await websocket.send_json({"type": step_type, "message": content})
            await websocket.send_json({"type": "done", "conversation_id": conv_id})
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass
