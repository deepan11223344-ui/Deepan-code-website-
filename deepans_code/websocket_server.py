"""
WebSocket server for DeepanCode streaming responses.
Provides real-time streaming of agent responses over WebSocket.
"""

import hmac
import json
import logging
import asyncio
import os
import time
import websockets
from typing import Dict, Set

logger = logging.getLogger("deepans_code.websocket")

# Store connected clients
connected_clients: Set = set()
# Map of conversation_id to clients subscribed
conversation_subscribers: Dict[str, Set] = {}

MAX_WS_MESSAGE_BYTES = 32768  # 32KB cap per message (DoS guard)
MAX_WS_MESSAGES_PER_MIN = 30
MAX_WS_CLIENTS = 200  # cap on authed sockets (state-exhaustion guard)
_ws_hits: Dict[int, list] = {}  # id(ws) -> timestamps


def _check_ws_token(token: str) -> bool:
    expected = os.environ.get("DEEPANCODE_API_TOKEN", "")
    if not expected:
        return False  # fail-closed
    return hmac.compare_digest(token or "", expected)


def _ws_rate_ok(ws) -> bool:
    now = time.time()
    # Opportunistic eviction so the map can't grow via dead sockets.
    for k in [k for k, v in _ws_hits.items() if not v or now - v[-1] >= 60]:
        _ws_hits.pop(k, None)
    key = id(ws)
    hits = [t for t in _ws_hits.get(key, []) if now - t < 60]
    if len(hits) >= MAX_WS_MESSAGES_PER_MIN:
        _ws_hits[key] = hits
        return False
    hits.append(now)
    _ws_hits[key] = hits
    return True


async def register_client(websocket, conversation_id: str = None):
    connected_clients.add(websocket)
    if conversation_id:
        if conversation_id not in conversation_subscribers:
            conversation_subscribers[conversation_id] = set()
        conversation_subscribers[conversation_id].add(websocket)
    logger.info(f"Client connected. Total: {len(connected_clients)}")


async def unregister_client(websocket, conversation_id: str = None):
    connected_clients.discard(websocket)
    _ws_hits.pop(id(websocket), None)
    for cid, subs in list(conversation_subscribers.items()):
        subs.discard(websocket)
        if not subs:
            del conversation_subscribers[cid]
    logger.info(f"Client disconnected. Total: {len(connected_clients)}")


async def broadcast_to_conversation(conversation_id: str, message: dict):
    if conversation_id in conversation_subscribers:
        dead = []
        for client in conversation_subscribers[conversation_id]:
            try:
                await client.send(json.dumps(message))
            except Exception:
                dead.append(client)
        for d in dead:
            conversation_subscribers[conversation_id].discard(d)


async def broadcast_all(message: dict):
    dead = []
    for client in connected_clients:
        try:
            await client.send(json.dumps(message))
        except Exception:
            dead.append(client)
    for d in dead:
        connected_clients.discard(d)


async def handle_message(websocket, message_str: str):
    if len(message_str.encode("utf-8", "ignore")) > MAX_WS_MESSAGE_BYTES:
        await websocket.send(json.dumps({"type": "error", "message": "Message too large (32KB max)"}))
        return
    if not _ws_rate_ok(websocket):
        await websocket.send(json.dumps({"type": "error", "message": "Rate limited, try again shortly"}))
        return
    try:
        data = json.loads(message_str)
        msg_type = data.get("type", "")

        # Auth gate: first message must carry {"type":"auth","token":"..."}
        # or every message must include a valid "token" field.
        authed = getattr(websocket, "_authed", False)
        token = data.get("token", "")
        if not authed:
            if not _check_ws_token(token):
                await websocket.send(json.dumps({"type": "error", "message": "Unauthorized: invalid DEEPANCODE_API_TOKEN"}))
                return
            websocket._authed = True
            if msg_type == "auth":
                await websocket.send(json.dumps({"type": "auth_ok"}))
                return

        if msg_type == "chat":
            # Forward to agent and stream back
            from deepans_code.agent import Agent
            from deepans_code.config import config_mgr

            try:
                conv_id = int(data.get("conversation_id")) if data.get("conversation_id") is not None else None
                if conv_id is not None and conv_id <= 0:
                    raise ValueError("bad id")
            except (ValueError, TypeError):
                await websocket.send(json.dumps({"type": "error", "message": "Invalid conversation_id"}))
                return
            user_input = str(data.get("message", ""))[:32768]
            if not user_input.strip():
                await websocket.send(json.dumps({"type": "error", "message": "message is required"}))
                return

            agent = Agent(conversation_id=conv_id)
            config_mgr.load(config_mgr.config_path)

            async for step_type, content in _stream_to_async(agent, user_input):
                await websocket.send(json.dumps({
                    "type": step_type,
                    "message": content
                }))

            # Send completion signal
            await websocket.send(json.dumps({
                "type": "done",
                "conversation_id": agent.conversation_id,
                "tokens": agent.get_token_usage()
            }))

        elif msg_type == "ping":
            await websocket.send(json.dumps({"type": "pong"}))

        elif msg_type == "subscribe":
            conv_id = data.get("conversation_id")
            try:
                cid = int(conv_id)
                if cid <= 0:
                    raise ValueError()
            except (ValueError, TypeError):
                await websocket.send(json.dumps({"type": "error", "message": "Invalid conversation_id"}))
                return
            await register_client(websocket, str(cid))

    except json.JSONDecodeError:
        await websocket.send(json.dumps({"type": "error", "message": "Invalid JSON"}))
    except Exception as e:
        logger.error(f"Handle message error: {e}")
        await websocket.send(json.dumps({"type": "error", "message": str(e)}))


async def _stream_to_async(agent, user_input):
    """Wrap synchronous generator into async generator."""
    import concurrent.futures
    loop = asyncio.get_running_loop()

    def run_stream():
        steps = []
        for step in agent.send_message_stream(user_input):
            steps.append(step)
        return steps

    steps = await loop.run_in_executor(None, run_stream)
    for step_type, content in steps:
        yield step_type, content
        await asyncio.sleep(0)  # yield control


async def ws_handler(websocket, path=None):
    conv_id = None
    authed_at = None
    try:
        # NOTE: no register_client() here on purpose — sockets are only
        # registered AFTER successful auth inside handle_message(), so
        # unauthenticated clients can never receive broadcasts nor occupy
        # subscriber state.
        async for message in websocket:
            if len(str(message).encode("utf-8", "ignore")) > MAX_WS_MESSAGE_BYTES:
                await websocket.send(json.dumps({"type": "error", "message": "Message too large"}))
                continue
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                await websocket.send(json.dumps({"type": "error", "message": "Invalid JSON"}))
                continue
            raw_cid = data.get("conversation_id")
            if raw_cid is not None:
                try:
                    cid = int(raw_cid)
                    if cid <= 0:
                        raise ValueError()
                    conv_id = str(cid)
                except (ValueError, TypeError):
                    await websocket.send(json.dumps({"type": "error", "message": "Invalid conversation_id"}))
                    continue
                # Subscription moves are deferred until auth succeeds: stash
                # the id; handle_message() registers it post-auth.
                websocket._pending_conv_id = conv_id
            was_authed = bool(getattr(websocket, "_authed", False))
            await handle_message(websocket, message)
            if not was_authed and getattr(websocket, "_authed", False):
                authed_at = time.time()
                if len(connected_clients) >= MAX_WS_CLIENTS:
                    await websocket.send(json.dumps({"type": "error", "message": "Server busy"}))
                    return
                await register_client(websocket)
                pending = getattr(websocket, "_pending_conv_id", None)
                if pending:
                    await register_client(websocket, pending)
    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        logger.error(f"WebSocket handler error: {e}")
    finally:
        await unregister_client(websocket, conv_id)


async def start_websocket_server(host="127.0.0.1", port=8765):
    async with websockets.serve(ws_handler, host, port):
        logger.info(f"WebSocket server started on ws://{host}:{port}")
        await asyncio.Future()  # run forever
