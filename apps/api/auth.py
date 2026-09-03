"""
Auth routes: invite-gated signup, password login (+TOTP step-up),
refresh rotation, logout, TOTP enroll/verify/disable.

No third parties: local credentials only (no OAuth — that would phone
Google/GitHub). Signup additionally requires an invite code so random
strangers cannot self-provision. Set DEEPANCODE_ALLOW_SIGNUP=false to
close registration entirely (pre-created users only).
"""

import os
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from deepans_code.security import csrf_protection

from . import ratelimit
from .crypto import (
    ACCESS_TTL,
    REFRESH_TTL,
    TOTP_TTL,
    hash_password,
    hash_token,
    mint_jwt,
    new_jti,
    new_totp_secret,
    otpauth_uri,
    verify_jwt,
    verify_password,
    verify_totp,
)
from .deps import ACCESS_COOKIE, REFRESH_COOKIE, client_ip, current_user
from .store import get_web_db

router = APIRouter(prefix="/api/auth", tags=["auth"])

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_SECONDS = 15 * 60


def _secure_cookies(request: Request) -> bool:
    if os.environ.get("DEEPANCODE_FORCE_SECURE", "").lower() in ("1", "true"):
        return True
    return request.url.scheme == "https"


def _set_session(response: Response, access: str, refresh: str, request: Request) -> None:
    secure = _secure_cookies(request)
    response.set_cookie(ACCESS_COOKIE, access, max_age=ACCESS_TTL,
                        httponly=True, secure=secure, samesite="lax", path="/")
    response.set_cookie(REFRESH_COOKIE, refresh, max_age=REFRESH_TTL,
                        httponly=True, secure=secure, samesite="lax",
                        path="/api/auth/refresh")
    # logout needs the refresh cookie too
    response.set_cookie(REFRESH_COOKIE + "_lo", refresh, max_age=REFRESH_TTL,
                        httponly=True, secure=secure, samesite="lax",
                        path="/api/auth/logout")


def _clear_session(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth/refresh")
    response.delete_cookie(REFRESH_COOKIE + "_lo", path="/api/auth/logout")


def _invite_ok(code: str) -> bool:
    if os.environ.get("DEEPANCODE_ALLOW_SIGNUP", "true").lower() in ("0", "false", "no"):
        return False
    expected = os.environ.get("DEEPANCODE_INVITE_CODE", "")
    if not expected:
        return False  # fail-closed: no code configured = no signup
    import hmac as _hmac
    return bool(code) and _hmac.compare_digest(code, expected)


class SignupIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)
    invite_code: str = Field(max_length=256)


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


class TotpLoginIn(BaseModel):
    ticket: str = Field(max_length=2048)
    code: str = Field(max_length=12)


class TotpVerifyIn(BaseModel):
    code: str = Field(max_length=12)


@router.post("/signup")
def signup(body: SignupIn, request: Request, response: Response):
    db = get_web_db()
    ip = client_ip(request)
    if not ratelimit.check("login", f"signup:{ip}"):
        raise HTTPException(status_code=429, detail="Too many attempts")
    if not _invite_ok(body.invite_code):
        db.audit("signup_denied", None, ip, "bad invite or closed")
        raise HTTPException(status_code=403, detail="Signup not allowed")
    if not EMAIL_RE.match(body.email or ""):
        raise HTTPException(status_code=400, detail="Invalid email")
    try:
        pwd_hash, salt = hash_password(body.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    is_admin = _user_count(db) == 0  # first account owns the instance
    uid = db.create_user(body.email, pwd_hash, salt, is_admin=is_admin)
    if not uid:
        raise HTTPException(status_code=409, detail="Email already registered")
    db.audit("signup", uid, ip, "account created")
    return _issue_session(db, uid, ip, request, response)


def _user_count(db) -> int:
    try:
        with db._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    except Exception:
        return 1


def _issue_session(db, uid: int, ip: str, request: Request, response: Response):
    access_jti, refresh_jti = new_jti(), new_jti()
    access = mint_jwt(str(uid), access_jti, "access", ACCESS_TTL)
    refresh = mint_jwt(str(uid), refresh_jti, "refresh", REFRESH_TTL)
    db.create_session(refresh_jti, uid, hash_token(refresh),
                      time.time() + REFRESH_TTL, ip,
                      request.headers.get("user-agent", ""))
    _set_session(response, access, refresh, request)
    csrf = csrf_protection.generate_token(access_jti)
    return {"user_id": uid, "session_id": access_jti, "csrf_token": csrf}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    db = get_web_db()
    ip = client_ip(request)
    if not ratelimit.check("login", f"login:{ip}"):
        raise HTTPException(status_code=429, detail="Too many attempts")
    user = db.get_user_by_email(body.email or "")
    # Constant-shape failure: never reveal whether the email exists.
    if user and time.time() < float(user.get("locked_until") or 0):
        db.audit("login_locked", user["id"], ip, "account locked")
        raise HTTPException(status_code=423, detail="Account locked, try later")
    ok = bool(user) and verify_password(
        body.password or "", user["pwd_hash"], user["pwd_salt"])
    if not ok:
        if user:
            fails = int(user.get("failed_attempts") or 0) + 1
            locked = time.time() + LOCKOUT_SECONDS if fails >= MAX_LOGIN_ATTEMPTS else 0
            db.set_login_state(user["id"], fails, locked)
            db.audit("login_fail", user["id"], ip, f"attempt {fails}")
        else:
            db.audit("login_fail", None, ip, "unknown email")
        # Burn equal work so unknown-email isn't faster (timing oracle).
        try:
            hash_password("dummy-timing-burn-0000")
        except ValueError:
            pass
        raise HTTPException(status_code=401, detail="Invalid email or password")
    db.set_login_state(user["id"], 0, 0)
    if user.get("totp_enabled"):
        ticket = mint_jwt(str(user["id"]), new_jti(), "totp_ticket", TOTP_TTL)
        db.audit("login_totp_required", user["id"], ip, "")
        return {"need_totp": True, "ticket": ticket}
    db.audit("login_ok", user["id"], ip, "")
    return _issue_session(db, user["id"], ip, request, response)


@router.post("/login/totp")
def login_totp(body: TotpLoginIn, request: Request, response: Response):
    db = get_web_db()
    ip = client_ip(request)
    if not ratelimit.check("login", f"totp:{ip}"):
        raise HTTPException(status_code=429, detail="Too many attempts")
    claims = verify_jwt(body.ticket or "", "totp_ticket")
    if not claims:
        raise HTTPException(status_code=401, detail="Expired ticket")
    user = db.get_user(int(claims["sub"]))
    if not user or not user.get("totp_enabled"):
        raise HTTPException(status_code=401, detail="Invalid ticket")
    if not verify_totp(user.get("totp_secret") or "", body.code or ""):
        db.audit("login_totp_fail", user["id"], ip, "")
        raise HTTPException(status_code=401, detail="Invalid code")
    db.audit("login_ok", user["id"], ip, "totp")
    return _issue_session(db, user["id"], ip, request, response)


@router.post("/refresh")
def refresh(request: Request, response: Response):
    db = get_web_db()
    ip = client_ip(request)
    token = request.cookies.get(REFRESH_COOKIE, "")
    if not ratelimit.check("refresh", f"refresh:{ip}"):
        raise HTTPException(status_code=429, detail="Too many attempts")
    claims = verify_jwt(token or "", "refresh")
    if not claims:
        raise HTTPException(status_code=401, detail="Invalid session")
    sess = db.get_session(claims["jti"])
    import hmac as _hmac
    if (not sess or sess.get("revoked") or float(sess.get("expires", 0)) < time.time()
            or not _hmac.compare_digest(sess.get("refresh_hash", ""), hash_token(token))):
        raise HTTPException(status_code=401, detail="Invalid session")
    # Rotation: old refresh dies with this use.
    db.revoke_session(claims["jti"])
    db.audit("refresh", int(claims["sub"]), ip, "")
    return _issue_session(db, int(claims["sub"]), ip, request, response)


@router.post("/logout")
def logout(request: Request, response: Response):
    db = get_web_db()
    token = request.cookies.get(REFRESH_COOKIE, "") or request.cookies.get(REFRESH_COOKIE + "_lo", "")
    claims = verify_jwt(token or "", "refresh") if token else None
    if claims:
        db.revoke_session(claims["jti"])
        db.audit("logout", int(claims["sub"]), client_ip(request), "")
    _clear_session(response)
    return {"status": "logged out"}


@router.post("/logout-all")
def logout_all(request: Request, response: Response, user: dict = Depends(current_user)):
    if user.get("service"):
        raise HTTPException(status_code=403, detail="Not available to service tokens")
    get_web_db().revoke_user_sessions(user["id"])
    get_web_db().audit("logout_all", user["id"], client_ip(request), "")
    _clear_session(response)
    return {"status": "all sessions revoked"}


@router.post("/totp/enroll")
def totp_enroll(request: Request, user: dict = Depends(current_user)):
    if user.get("service"):
        raise HTTPException(status_code=403, detail="Not available to service tokens")
    from .deps import require_csrf
    require_csrf(request, user)
    db = get_web_db()
    secret = new_totp_secret()
    db.set_totp(user["id"], secret, False)
    db.audit("totp_enroll", user["id"], client_ip(request), "")
    u = db.get_user(user["id"])
    return {"otpauth_uri": otpauth_uri(secret, u["email"]), "secret": secret}


@router.post("/totp/verify")
def totp_verify(body: TotpVerifyIn, request: Request, user: dict = Depends(current_user)):
    if user.get("service"):
        raise HTTPException(status_code=403, detail="Not available to service tokens")
    from .deps import require_csrf
    require_csrf(request, user)
    db = get_web_db()
    u = db.get_user(user["id"])
    if not u or not u.get("totp_secret"):
        raise HTTPException(status_code=400, detail="Enroll first")
    if not verify_totp(u["totp_secret"], body.code or ""):
        raise HTTPException(status_code=401, detail="Invalid code")
    db.set_totp(user["id"], u["totp_secret"], True)
    db.audit("totp_enabled", user["id"], client_ip(request), "")
    return {"status": "2FA enabled"}


@router.post("/totp/disable")
def totp_disable(body: TotpVerifyIn, request: Request, user: dict = Depends(current_user)):
    if user.get("service"):
        raise HTTPException(status_code=403, detail="Not available to service tokens")
    from .deps import require_csrf
    require_csrf(request, user)
    db = get_web_db()
    u = db.get_user(user["id"])
    if not u or not u.get("totp_enabled") or not verify_totp(u.get("totp_secret") or "", body.code or ""):
        raise HTTPException(status_code=401, detail="Invalid code")
    db.set_totp(user["id"], "", False)
    db.audit("totp_disabled", user["id"], client_ip(request), "")
    return {"status": "2FA disabled"}


@router.get("/csrf-token")
def csrf_token(request: Request, user: dict = Depends(current_user)):
    if user.get("service"):
        raise HTTPException(status_code=403, detail="Not available to service tokens")
    token = csrf_protection.generate_token(user["jti"])
    return {"session_id": user["jti"], "csrf_token": token}
