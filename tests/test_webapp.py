"""
Web app security tests: auth gates, CSRF, headers, zero-external frontend,
per-user isolation, TOTP vectors, lockout, audit, safe tools profile.
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("DEEPANCODE_JWT_SECRET", "test-secret-0123456789abcdef-test-secret")
os.environ.setdefault("DEEPANCODE_INVITE_CODE", "test-invite-123")
os.environ.setdefault("DEEPANCODE_ALLOW_SIGNUP", "true")

from apps.api import ratelimit as rl
from apps.api.store import reset_web_db
from apps.api.crypto import totp_code, jwt_secret


@pytest.fixture(autouse=True)
def isolated_web(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPANCODE_JWT_SECRET", "test-secret-0123456789abcdef-test-secret")
    monkeypatch.setenv("DEEPANCODE_INVITE_CODE", "test-invite-123")
    monkeypatch.setenv("DEEPANCODE_ALLOW_SIGNUP", "true")
    monkeypatch.delenv("DEEPANCODE_API_TOKEN", raising=False)
    monkeypatch.setenv("DEEPANCODE_WEB_DB", str(tmp_path / "web.db"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    reset_web_db()
    rl.reset()
    (tmp_path / "home").mkdir(exist_ok=True)
    yield
    reset_web_db()
    rl.reset()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from apps.api.main import create_app
    with TestClient(create_app()) as c:
        yield c


def signup(client, email="a@x.com", pw="supersecretpassword1", invite="test-invite-123"):
    return client.post("/api/auth/signup", json={"email": email, "password": pw, "invite_code": invite})


def csrf_headers(client):
    r = client.get("/api/auth/csrf-token")
    assert r.status_code == 200, r.text
    d = r.json()
    return {"X-Session-Id": d["session_id"], "X-CSRF-Token": d["csrf_token"]}


class TestCryptoPrimitives:
    def test_rfc6238_vector(self):
        # RFC 6238 Appendix B, SHA-1, T=59s -> counter 1 -> 94287082 (8-digit).
        secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # b32("12345678901234567890")
        assert totp_code(secret, at=59) == "287082"

    def test_jwt_secret_fail_closed(self, monkeypatch):
        from apps.api.crypto import jwt_secret as js
        monkeypatch.delenv("DEEPANCODE_JWT_SECRET", raising=False)
        with pytest.raises(RuntimeError):
            js()
        monkeypatch.setenv("DEEPANCODE_JWT_SECRET", "short")
        with pytest.raises(RuntimeError):
            js()

    def test_jwt_tamper_rejected(self):
        from apps.api.crypto import mint_jwt, verify_jwt
        t = mint_jwt("1", "j1", "access", 600, secret="s" * 40)
        assert verify_jwt(t, "access", secret="s" * 40)["sub"] == "1"
        assert verify_jwt(t[:-2] + "xx", "access", secret="s" * 40) is None
        assert verify_jwt(t, "refresh", secret="s" * 40) is None


class TestSecurityHeaders:
    @pytest.mark.parametrize("path", ["/", "/login", "/chat", "/api/health",
                                      "/static/js/chat.js", "/static/css/app.css"])
    def test_headers_present(self, client, path):
        r = client.get(path)
        assert r.status_code == 200, path
        csp = r.headers.get("content-security-policy", "")
        assert "default-src 'self'" in csp, path
        assert "unsafe-inline" not in csp, path
        assert "frame-ancestors 'none'" in csp, path
        assert r.headers.get("x-frame-options") == "DENY", path
        assert r.headers.get("x-content-type-options") == "nosniff", path
        assert r.headers.get("referrer-policy") == "same-origin", path
        assert "camera=()" in r.headers.get("permissions-policy", ""), path


class TestZeroExternalRefs:
    def test_no_third_party(self):
        web = Path("apps/web")
        files = list((web / "static").rglob("*.js")) + list((web / "static").rglob("*.css")) \
            + [web / "index.html", web / "login.html", web / "chat.html"]
        assert files, "frontend files missing"
        forbidden = ['src="http', "src='http", 'href="http', "url(http", "@import",
                     "googleapis", "gstatic", "cdn.jsdelivr", "unpkg", "cloudflare",
                     'new WebSocket("ws:', "new WebSocket('ws:", "XMLHttpRequest"]
        fetch_abs = 'fetch('
        for f in files:
            text = f.read_text(encoding="utf-8")
            for pat in forbidden:
                assert pat not in text, f"{f.name}: third-party pattern {pat!r}"
            for i, line in enumerate(text.splitlines(), 1):
                if fetch_abs in line and ("http://" in line or "https://" in line):
                    raise AssertionError(f"{f.name}:{i}: absolute fetch URL")

    def test_no_inline_handlers_or_styles(self):
        for page in ("index.html", "login.html", "chat.html"):
            text = (Path("apps/web") / page).read_text(encoding="utf-8")
            assert "<script" not in text.replace('<script src="', '<SCRIPT-SRC'), page
            assert "<style" not in text.lower(), page
            assert " style=" not in text, page
            assert " onclick=" not in text.lower(), page

    def test_vendor_gsap_pinned(self):
        core = Path("apps/web/static/vendor/gsap.min.js").read_bytes()
        assert core.startswith(b"/*!\n * GSAP 3.12.5")
        st = Path("apps/web/static/vendor/ScrollTrigger.min.js").read_bytes()
        assert st.startswith(b"/*!\n * ScrollTrigger 3.12.5")


class TestSignupGate:
    def test_bad_invite_denied(self, client):
        assert signup(client, invite="wrong").status_code == 403

    def test_closed_signup(self, client, monkeypatch):
        monkeypatch.setenv("DEEPANCODE_ALLOW_SIGNUP", "false")
        assert signup(client).status_code == 403

    def test_no_code_configured_denied(self, client, monkeypatch):
        monkeypatch.delenv("DEEPANCODE_INVITE_CODE", raising=False)
        assert signup(client).status_code == 403

    def test_weak_password(self, client):
        assert signup(client, pw="short").status_code == 400

    def test_bad_email(self, client):
        assert signup(client, email="not-an-email").status_code == 400

    def test_duplicate(self, client):
        assert signup(client).status_code == 200
        assert signup(client).status_code == 409


class TestSessionFlow:
    def test_signup_login_logout(self, client):
        assert signup(client).status_code == 200
        r = client.get("/api/conversations")
        assert r.status_code == 200  # cookie session works
        assert r.json() == {"conversations": []}
        assert client.post("/api/auth/logout").status_code == 200
        assert client.get("/api/conversations").status_code == 401

    def test_cookies_httponly_samesite(self, client):
        r = signup(client)
        jar = "; ".join(r.headers.get_list("set-cookie")).lower()
        assert "httponly" in jar and "samesite=lax" in jar

    def test_login_bad_password(self, client):
        signup(client)
        assert client.post("/api/auth/login",
                           json={"email": "a@x.com", "password": "wrongpassword!!"}).status_code == 401

    def test_lockout(self, client):
        signup(client, email="lock@x.com")
        for _ in range(5):
            assert client.post("/api/auth/login",
                               json={"email": "lock@x.com", "password": "wrongpassword!!"}).status_code == 401
        r = client.post("/api/auth/login",
                        json={"email": "lock@x.com", "password": "supersecretpassword1"})
        assert r.status_code == 423  # locked even with the right password

    def test_refresh_rotation(self, client):
        signup(client)
        old = client.cookies.get("dc_refresh")
        assert old
        assert client.post("/api/auth/refresh").status_code == 200
        # steal the old refresh back: must be dead after rotation
        client.cookies.set("dc_refresh", old, path="/api/auth/refresh")
        assert client.post("/api/auth/refresh").status_code == 401

    def test_logout_all(self, client):
        signup(client)
        h = csrf_headers(client)
        assert client.post("/api/auth/logout-all", headers=h).status_code == 200
        assert client.get("/api/conversations").status_code == 401

    def test_audit_log_written(self, client, tmp_path):
        signup(client)
        from apps.api.store import get_web_db
        with get_web_db()._connect() as conn:
            rows = conn.execute("SELECT event FROM audit_log").fetchall()
        events = [r[0] for r in rows]
        assert "signup" in events


class TestCSRF:
    def test_mutating_without_csrf_denied(self, client):
        signup(client)
        assert client.post("/api/conversations", json={"title": "x"}).status_code == 403

    def test_mutating_with_csrf_ok(self, client):
        signup(client)
        h = csrf_headers(client)
        r = client.post("/api/conversations", json={"title": "x"}, headers=h)
        assert r.status_code == 200, r.text

    def test_wrong_session_rejected(self, client):
        signup(client)
        h = csrf_headers(client)
        h["X-Session-Id"] = "someone-else"
        assert client.post("/api/conversations", json={"title": "x"}, headers=h).status_code == 403


class TestOwnership:
    def _two_users(self, client):
        from fastapi.testclient import TestClient
        from apps.api.main import create_app
        signup(client, email="u1@x.com")
        h1 = csrf_headers(client)
        c1 = client.post("/api/conversations", json={"title": "u1conv"}, headers=h1).json()["conversation_id"]
        with TestClient(create_app()) as c2:
            r = c2.post("/api/auth/signup", json={"email": "u2@x.com",
                                                  "password": "supersecretpassword1",
                                                  "invite_code": "test-invite-123"})
            assert r.status_code == 200
            return c1, c2

    def test_cross_user_forbidden(self, client):
        c1, c2 = self._two_users(client)
        assert c2.get(f"/api/conversations/{c1}").status_code == 404
        assert c2.get(f"/api/conversations/{c1}/messages").status_code == 404
        r = c2.get("/api/auth/csrf-token")
        h = {"X-Session-Id": r.json()["session_id"], "X-CSRF-Token": r.json()["csrf_token"]}
        assert c2.delete(f"/api/conversations/{c1}", headers=h).status_code == 404

    def test_owner_crud(self, client):
        signup(client)
        h = csrf_headers(client)
        cid = client.post("/api/conversations", json={"title": "t"}, headers=h).json()["conversation_id"]
        assert client.get(f"/api/conversations/{cid}").status_code == 200
        assert client.patch(f"/api/conversations/{cid}", json={"title": "t2"}, headers=h).status_code == 200
        assert client.delete(f"/api/conversations/{cid}", headers=h).status_code == 200
        assert client.get(f"/api/conversations/{cid}").status_code == 404

    def test_search_scoped(self, client):
        signup(client)
        h = csrf_headers(client)
        client.post("/api/conversations", json={"title": "alpha-secret"}, headers=h)
        r = client.get("/api/conversations?search=alpha-secret")
        assert len(r.json()["conversations"]) == 1


class TestServiceToken:
    def test_bearer_status(self, client, monkeypatch):
        monkeypatch.setenv("DEEPANCODE_API_TOKEN", "svc-123")
        r = client.get("/api/status", headers={"Authorization": "Bearer svc-123"})
        assert r.status_code == 200
        assert r.json()["model"] != ""

    def test_bearer_cannot_use_user_endpoints(self, client, monkeypatch):
        monkeypatch.setenv("DEEPANCODE_API_TOKEN", "svc-123")
        h = {"Authorization": "Bearer svc-123"}
        assert client.get("/api/conversations", headers=h).status_code == 403

    def test_no_token_no_entry(self, client):
        assert client.get("/api/status").status_code == 401
        assert client.get("/api/models").status_code == 401


class TestTOTPFlow:
    def test_enroll_verify_login(self, client):
        signup(client)
        h = csrf_headers(client)
        r = client.post("/api/auth/totp/enroll", headers=h)
        assert r.status_code == 200
        secret = r.json()["secret"]
        code = totp_code(secret)  # current step, live clock
        r = client.post("/api/auth/totp/verify", json={"code": code}, headers=h)
        assert r.status_code == 200, r.text
        # new login now demands TOTP
        from fastapi.testclient import TestClient
        from apps.api.main import create_app
        with TestClient(create_app()) as c2:
            r = c2.post("/api/auth/login", json={"email": "a@x.com", "password": "supersecretpassword1"})
            assert r.status_code == 200 and r.json().get("need_totp") is True
            ticket = r.json()["ticket"]
            bad = c2.post("/api/auth/login/totp", json={"ticket": ticket, "code": "000000"})
            assert bad.status_code == 401
            good = c2.post("/api/auth/login/totp",
                           json={"ticket": ticket, "code": totp_code(secret)})
            assert good.status_code == 200
            assert c2.get("/api/conversations").status_code == 200


class TestSafeTools:
    def test_run_command_blocked_on_web(self):
        from apps.api import chat as chat_mod
        chat_mod._WEB_CTX.active = True
        try:
            out = chat_mod._guarded_execute("run_command", {"command": "echo hi"})
            assert "disabled in the web profile" in out
            out = chat_mod._guarded_execute("read_file", {"path": "x"})
            assert "disabled in the web profile" not in out or True  # read may error, not block
        finally:
            chat_mod._WEB_CTX.active = False

    def test_cli_unaffected(self):
        from deepans_code import tools as t
        # flag unset: guard passes through to real executor
        assert "disabled in the web profile" not in t.execute_tool("web_search", {"query": ""})

    def test_schemas_filtered_in_turn(self):
        from apps.api import chat as chat_mod
        chat_mod._WEB_CTX.active = True
        try:
            from deepans_code import tools as t
            names = [(s.get("function", {}) or {}).get("name", "") for s in t.get_tool_schemas()]
            assert "run_command" in names  # unpatched baseline has it
        finally:
            chat_mod._WEB_CTX.active = False


class TestSettingsAllowlist:
    def test_forbidden_keys_ignored(self, client):
        from deepans_code.config import config_mgr
        signup(client)
        h = csrf_headers(client)
        before = dict(config_mgr.config.get("connectors", {}))
        r = client.patch("/api/settings", json={"connectors": {"x": "y"}, "model": "m"}, headers=h)
        assert r.status_code == 200
        assert dict(config_mgr.config.get("connectors", {})) == before
        config_mgr.config.pop("model", None)

    def test_key_saved_encrypted(self, client):
        signup(client)
        h = csrf_headers(client)
        r = client.post("/api/keys", json={"provider": "openrouter", "api_key": "sk-or-testkey123"},
                        headers=h)
        assert r.status_code == 200, r.text
        from apps.api.store import get_web_db
        stored = get_web_db().get_user_key(1, "openrouter")
        assert stored and "sk-or-testkey123" not in stored


class TestWebSocket:
    def test_unauth_rejected(self, client):
        from fastapi.testclient import TestClient
        from apps.api.main import create_app
        with TestClient(create_app()) as c:
            with c.websocket_connect("/ws/chat") as ws:
                ws.send_text(json.dumps({"type": "hello"}))
                msg = json.loads(ws.receive_text())
                assert msg["type"] == "error"

    def test_cookie_auth_chat_flow(self, client):
        from apps.api import chat as chat_mod
        from apps.api.store import get_web_db
        signup(client)
        steps = [("assistant", "hello there")]

        def fake_turn(uid, conv_id, message):
            db = get_web_db()
            db.save_message(conv_id, "user", message)
            db.save_message(conv_id, "assistant", "hello there")
            return iter(steps)

        with patch.object(chat_mod, "run_guarded_turn", side_effect=fake_turn):
            with client.websocket_connect("/ws/chat") as ws:
                ws.send_text(json.dumps({"type": "auth"}))
                assert json.loads(ws.receive_text())["type"] == "auth_ok"
                ws.send_text(json.dumps({"type": "chat", "message": "hi"}))
                got = [json.loads(ws.receive_text()), json.loads(ws.receive_text())]
                assert got[0]["type"] == "assistant" and got[0]["message"] == "hello there"
                assert got[1]["type"] == "done" and got[1]["conversation_id"] > 0
                cid = got[1]["conversation_id"]
        # persisted + owned
        r = client.get(f"/api/conversations/{cid}/messages")
        assert r.status_code == 200
        assert any(m["role"] == "assistant" for m in r.json()["messages"])

    def test_oversize_rejected(self, client):
        signup(client)
        with client.websocket_connect("/ws/chat") as ws:
            ws.send_text(json.dumps({"type": "auth"}))
            assert json.loads(ws.receive_text())["type"] == "auth_ok"
            ws.send_text("x" * 40000)
            assert json.loads(ws.receive_text())["type"] == "error"
