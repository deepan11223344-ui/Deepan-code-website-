"""
Request identity + CSRF enforcement.

Identity sources (in order):
1. HttpOnly session cookie `dc_access` (browser web UI).
2. `Authorization: Bearer <DEEPANCODE_API_TOKEN>` (service/CLI only —
   never mints user identity; marked service=True).

CSRF rule: any request carrying the session cookie on a mutating method
(POST/PUT/PATCH/DELETE) must ALSO present a valid X-Session-Id +
X-CSRF-Token pair bound to the access-token jti. Bearer-only requests
are non-browser by definition and skip CSRF.
"""

import os

from fastapi import HTTPException, Request

from deepans_code.security import csrf_protection

from .crypto import verify_jwt
from .store import get_web_db

ACCESS_COOKIE = "dc_access"
REFRESH_COOKIE = "dc_refresh"


def _service_authed(request: Request) -> bool:
    expected = os.environ.get("DEEPANCODE_API_TOKEN", "")
    if not expected:
        return False
    import hmac as _hmac

    got = request.headers.get("authorization", "")
    if got.lower().startswith("bearer "):
        got = got[7:].strip()
    return bool(got) and _hmac.compare_digest(got, expected)


def current_user(request: Request) -> dict:
    """Returns {'id', 'email', 'jti', 'service'} or raises 401."""
    token = request.cookies.get(ACCESS_COOKIE, "")
    if token:
        claims = verify_jwt(token, "access")
        if claims:
            user = get_web_db().get_user(int(claims["sub"]))
            if user:
                return {"id": user["id"], "email": user["email"],
                        "jti": claims["jti"], "service": False}
    if _service_authed(request):
        return {"id": 0, "email": "service", "jti": "service", "service": True}
    raise HTTPException(status_code=401, detail="Unauthorized")


def require_csrf(request: Request, user: dict) -> None:
    """Enforce CSRF for cookie-authed mutating requests."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if user.get("service"):
        return  # bearer-only: non-browser client
    if not request.cookies.get(ACCESS_COOKIE):
        return  # no cookie, nothing to forge
    session_id = request.headers.get("x-session-id", "")
    token = request.headers.get("x-csrf-token", "")
    # Token is bound to the access-token jti: stolen tokens don't transfer.
    if session_id != user.get("jti") or not csrf_protection.validate_token(session_id, token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()[:100]
    return (request.client.host if request.client else "")[:100]
