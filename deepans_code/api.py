"""
REST API + WebSocket endpoint for DeepanCode.
Provides HTTP API for chat, conversations, health, and status.
"""

import json
import logging
import os
from typing import Dict, Any
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import threading

from deepans_code.config import config_mgr
from deepans_code.database import db
from deepans_code.models import get_all_models, get_model_info, get_model_context_window
from deepans_code.agent import Agent
from deepans_code import __version__

logger = logging.getLogger("deepans_code.api")

MAX_BODY_BYTES = 1_000_000  # 1 MB cap on request bodies (DoS guard)


def get_allowed_origins() -> list:
    """CORS allowlist. Configure via DEEPANCODE_ALLOWED_ORIGINS (comma-separated)."""
    raw = os.environ.get("DEEPANCODE_ALLOWED_ORIGINS", "http://127.0.0.1:8080,http://localhost:8080")
    return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]


def _is_origin_allowed(origin: str) -> bool:
    if not origin:
        return False
    return origin.rstrip("/") in get_allowed_origins()


class DeepanCodeAPIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logger.debug(f"API: {args[0]}")

    def _send_json(self, data: Dict, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        origin = self.headers.get("Origin", "")
        if _is_origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())

    def _check_auth(self) -> bool:
        # Fail-closed bearer auth: DEEPANCODE_API_TOKEN is REQUIRED for every
        # /api/* endpoint except /api/health. If the env var is unset the
        # server refuses all protected calls (previous behaviour was open).
        expected = os.environ.get("DEEPANCODE_API_TOKEN", "")
        if not expected:
            logger.warning("DEEPANCODE_API_TOKEN unset — denying authenticated endpoint")
            return False
        got = self.headers.get("Authorization", "")
        if got.startswith("Bearer "):
            got = got[7:]
        import hmac as _hmac
        return _hmac.compare_digest(got, expected)

    @staticmethod
    def _extract_conv_id(path: str) -> int | None:
        # Safe path parsing: /api/conversations/<id>[/messages]
        # Returns None instead of raising IndexError on malformed paths.
        try:
            segs = [s for s in path.split("/") if s]
            # expect ['api','conversations','<id>', ...]
            if len(segs) < 3 or segs[0] != "api" or segs[1] != "conversations":
                return None
            cid = int(segs[2].strip())
            return cid if cid > 0 else None
        except (ValueError, TypeError, AttributeError):
            return None

    def _read_body(self) -> Dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return {}
        if length == 0:
            return {}
        if length > MAX_BODY_BYTES:
            raise ValueError("Request body too large")
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as e:
            raise ValueError(f"Invalid JSON body: {e}")

    def do_OPTIONS(self):
        self.send_response(200)
        origin = self.headers.get("Origin", "")
        if _is_origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization, X-Session-Id, X-CSRF-Token",
        )
        self.end_headers()

    def _require_auth(self) -> bool:
        if not self._check_auth():
            self._send_json({"error": "Unauthorized: set DEEPANCODE_API_TOKEN"}, 401)
            return False
        return True

    def _require_csrf(self) -> bool:
        """Browser CSRF gate for mutating requests.

        Non-browser clients (no Origin header, e.g. CLI/curl) rely on the
        bearer token alone. Browser clients (Origin present) must additionally
        present a valid X-Session-Id + X-CSRF-Token pair previously minted
        via GET /api/csrf-token. Uses security.csrf_protection.
        """
        origin = self.headers.get("Origin", "")
        if not origin:
            return True  # non-browser: bearer suffices
        if not _is_origin_allowed(origin):
            self._send_json({"error": "Origin not allowed"}, 403)
            return False
        from deepans_code.security import csrf_protection
        session_id = self.headers.get("X-Session-Id", "")
        token = self.headers.get("X-CSRF-Token", "")
        if not csrf_protection.validate_token(session_id, token):
            self._send_json({"error": "Invalid CSRF token"}, 403)
            return False
        return True

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/api/health":
            self._handle_health()
            return
        # All other GET endpoints are protected (fail-closed).
        if not self._require_auth():
            return

        if path == "/api/status":
            self._handle_status()
        elif path == "/api/models":
            self._handle_models()
        elif path == "/api/csrf-token":
            self._handle_csrf_token()
        elif path == "/api/conversations":
            self._handle_list_conversations()
        elif path.endswith("/messages") and "/api/conversations/" in path:
            conv_id = self._extract_conv_id(path)
            if conv_id is None:
                self._send_json({"error": "Invalid conversation id"}, 400)
                return
            self._handle_get_messages(conv_id)
        elif path.startswith("/api/conversations/"):
            conv_id = self._extract_conv_id(path)
            if conv_id is None:
                self._send_json({"error": "Invalid conversation id"}, 400)
                return
            self._handle_get_conversation(conv_id)
        else:
            self._send_json({"error": "Not found"}, 404)

    def _parse_conv_id(self, raw) -> int | None:
        try:
            cid = int(str(raw).strip())
            return cid if cid > 0 else None
        except (ValueError, TypeError, AttributeError):
            return None

    def do_POST(self):
        if not self._require_auth():
            return
        if not self._require_csrf():
            return
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        try:
            if path == "/api/chat":
                self._handle_chat()
            elif path == "/api/conversations":
                self._handle_create_conversation()
            elif path == "/api/config":
                self._handle_set_config()
            else:
                self._send_json({"error": "Not found"}, 404)
        except ValueError as e:
            self._send_json({"error": str(e)}, 400)

    def do_DELETE(self):
        if not self._require_auth():
            return
        if not self._require_csrf():
            return
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path.startswith("/api/conversations/"):
            conv_id = self._extract_conv_id(path)
            if conv_id is None:
                self._send_json({"error": "Invalid conversation id"}, 400)
                return
            self._handle_delete_conversation(conv_id)
        else:
            self._send_json({"error": "Not found"}, 404)

    def _handle_health(self):
        self._send_json({"status": "healthy", "version": __version__})

    def _handle_csrf_token(self):
        from deepans_code.security import csrf_protection
        import secrets
        # Session id: client-provided or freshly minted.
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query or "")
        session_id = (qs.get("session_id", [""])[0] or self.headers.get("X-Session-Id", "")).strip()
        if not session_id:
            session_id = secrets.token_urlsafe(16)
        token = csrf_protection.generate_token(session_id)
        self._send_json({"session_id": session_id, "csrf_token": token})

    def _handle_status(self):
        model = config_mgr.get("model", "openrouter/free")
        provider = config_mgr.get("provider", "openrouter")
        self._send_json({
            "model": model,
            "provider": provider,
            "mode": config_mgr.get("mode", "code"),
            "db_stats": db.get_stats()
        })

    def _handle_models(self):
        self._send_json({"models": get_all_models()})

    def _handle_chat(self):
        from deepans_code.security import rate_limiter
        if not rate_limiter.allow("api:chat"):
            self._send_json({"error": "Rate limited, try again shortly"}, 429)
            return
        data = self._read_body()
        message = str(data.get("message", ""))[:32768]
        raw_cid = data.get("conversation_id")
        conv_id = self._parse_conv_id(raw_cid) if raw_cid is not None else None
        if raw_cid is not None and conv_id is None:
            self._send_json({"error": "Invalid conversation_id"}, 400)
            return
        if not message.strip():
            self._send_json({"error": "message is required"}, 400)
            return
        try:
            agent = Agent(conversation_id=conv_id)
            steps = agent.send_message(message)
        except Exception as e:
            logger.error(f"Chat handler error: {e}", exc_info=True)
            self._send_json({"error": "Agent failed to process message"}, 500)
            return
        response_parts = [c for t, c in steps if t == "assistant"]
        self._send_json({
            "response": "\n".join(response_parts),
            "conversation_id": agent.conversation_id,
            "tokens": agent.get_token_usage()
        })

    def _handle_create_conversation(self):
        data = self._read_body()
        conv_id = db.create_conversation(
            title=data.get("title", "Untitled"),
            model=config_mgr.get("model", ""),
            provider=config_mgr.get("provider", "")
        )
        self._send_json({"conversation_id": conv_id})

    def _handle_list_conversations(self):
        convs = db.get_conversations()
        self._send_json({"conversations": convs})

    def _handle_get_conversation(self, conv_id):
        cid = self._parse_conv_id(conv_id)
        if cid is None:
            self._send_json({"error": "Invalid conversation id"}, 400)
            return
        conv = db.get_conversation(cid)
        if conv:
            self._send_json(conv)
        else:
            self._send_json({"error": "Not found"}, 404)

    def _handle_get_messages(self, conv_id):
        cid = self._parse_conv_id(conv_id)
        if cid is None:
            self._send_json({"error": "Invalid conversation id"}, 400)
            return
        messages = db.get_messages(cid)
        self._send_json({"messages": messages})

    def _handle_delete_conversation(self, conv_id):
        cid = self._parse_conv_id(conv_id)
        if cid is None:
            self._send_json({"error": "Invalid conversation id"}, 400)
            return
        db.delete_conversation(cid)
        self._send_json({"status": "deleted"})

    def _handle_set_config(self):
        data = self._read_body()
        allowed = {"model", "provider", "effort", "mode", "agent", "thinking", "theme"}
        for key, value in data.items():
            if key not in allowed:
                continue  # never allow connectors/api keys via unauthenticated HTTP
            config_mgr.set(key, value)
        self._send_json({"status": "updated"})


class APIServer:
    def __init__(self, host="127.0.0.1", port=8080):
        self.host = host
        self.port = port
        self._server = None
        self._thread = None

    def start_background(self):
        self._server = HTTPServer((self.host, self.port), DeepanCodeAPIHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info(f"API server started on http://{self.host}:{self.port}")

    def stop(self):
        if self._server:
            self._server.shutdown()


api_server = APIServer()
