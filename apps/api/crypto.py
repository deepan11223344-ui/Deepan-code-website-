"""
Web auth crypto for DeepanCode. Deliberately stdlib-only (hashlib/hmac/
secrets/struct/base64): passwords (PBKDF2-SHA256), sessions (HS256 JWT),
second factor (RFC 6238 TOTP). No new supply-chain beyond FastAPI itself.
"""

import base64
import hashlib
import hmac
import json
import secrets
import struct
import time

# OWASP PBKDF2 guidance: SHA-256, >=600k iterations, unique 16B+ salt.
PBKDF2_ITERATIONS = 600_000
ACCESS_TTL = 15 * 60
REFRESH_TTL = 30 * 24 * 3600
TOTP_TTL = 5 * 60
TOTP_STEP = 30
TOTP_DIGITS = 6


def hash_password(password: str) -> tuple:
    """Returns (hash_hex, salt_hex). Rejects weak passwords fail-closed."""
    if not isinstance(password, str) or len(password) < 12:
        raise ValueError("Password must be at least 12 characters")
    if len(password) > 256:
        raise ValueError("Password too long")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return digest.hex(), salt.hex()


def verify_password(password: str, hash_hex: str, salt_hex: str) -> bool:
    try:
        if not isinstance(password, str) or not hash_hex or not salt_hex:
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def jwt_secret() -> str:
    """Fail-closed: the server refuses authenticated operation without a key."""
    import os

    secret = os.environ.get("DEEPANCODE_JWT_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError(
            "DEEPANCODE_JWT_SECRET must be set with at least 32 characters. "
            "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )
    return secret


def mint_jwt(sub: str, jti: str, kind: str, ttl: int, secret: str = None) -> str:
    now = int(time.time())
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64url(json.dumps(
        {"sub": sub, "jti": jti, "type": kind, "iat": now, "exp": now + int(ttl)},
        separators=(",", ":"),
    ).encode())
    key = (secret or jwt_secret()).encode("utf-8")
    sig = _b64url(hmac.new(key, f"{header}.{body}".encode(), hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"


def verify_jwt(token: str, expect_kind: str, secret: str = None, leeway: int = 30) -> dict | None:
    """Returns claims dict or None. Constant-time signature check."""
    try:
        if not isinstance(token, str):
            return None
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header, body, sig = parts
        key = (secret or jwt_secret()).encode("utf-8")
        expected = _b64url(hmac.new(key, f"{header}.{body}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        claims = json.loads(_b64url_decode(body))
        if claims.get("type") != expect_kind:
            return None
        now = int(time.time())
        if int(claims.get("exp", 0)) < now - leeway:
            return None
        if int(claims.get("iat", now + 1)) > now + leeway:
            return None
        return claims
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def new_jti() -> str:
    return secrets.token_urlsafe(18)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# -- TOTP (RFC 6238, SHA-1, 30s step, 6 digits) -------------------------------
def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def totp_code(secret_b32: str, at: int = None) -> str:
    try:
        key = base64.b32decode(secret_b32.strip().replace(" ", "").upper())
    except Exception:
        raise ValueError("Invalid TOTP secret")
    counter = int((at if at is not None else time.time()) // TOTP_STEP)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    code = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** TOTP_DIGITS)).zfill(TOTP_DIGITS)


def verify_totp(secret_b32: str, code: str, at: int = None, window: int = 1) -> bool:
    """Accepts codes from adjacent steps (clock skew). No early exit oracle."""
    if not isinstance(code, str) or not code.isdigit():
        return False
    now = at if at is not None else time.time()
    ok = False
    for step in range(-window, window + 1):
        try:
            candidate = totp_code(secret_b32, at=now + step * TOTP_STEP)
        except ValueError:
            return False
        if hmac.compare_digest(candidate, code.strip()):
            ok = True
    return ok


def otpauth_uri(secret_b32: str, account: str, issuer: str = "DeepanCode") -> str:
    import urllib.parse

    label = urllib.parse.quote(f"{issuer}:{account}")
    params = urllib.parse.urlencode({"secret": secret_b32, "issuer": issuer, "digits": 6, "period": 30})
    return f"otpauth://totp/{label}?{params}"
