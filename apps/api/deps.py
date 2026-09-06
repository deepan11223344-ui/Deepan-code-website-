"""
Request identity + CSRF enforcement.

No authentication required — all requests are treated as the default user.
"""

from fastapi import Request


ACCESS_COOKIE = "dc_access"
REFRESH_COOKIE = "dc_refresh"


def current_user(request: Request) -> dict:
    """Returns default user dict — no auth required."""
    return {"id": 1, "email": "user@deepancode.local", "jti": "default", "service": False}


def require_csrf(request: Request, user: dict) -> None:
    """No CSRF enforcement needed without auth."""
    pass


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()[:100]
    return (request.client.host if request.client else "")[:100]
