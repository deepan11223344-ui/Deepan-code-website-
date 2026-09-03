"""
Security module for DeepanCode.
Command sandboxing, workspace boundary, input sanitization, AES-256 encryption,
rate limiting, and CSRF protection.
"""

import os
import re
import time
import base64
import hashlib
import hmac
import logging
import secrets
import shlex
from pathlib import Path
from typing import Optional, Set, List, Tuple, Dict
from collections import defaultdict
import threading

logger = logging.getLogger("deepans_code.security")

# Safe commands allowlist (minimal default; interpreters / package-managers /
# env-dumpers require explicit opt-in via extra_safe because they allow
# arbitrary code execution or secret exfiltration, e.g.
# `python -c "shutil.rmtree(...)"` or `env` leaking keys to the LLM).
SAFE_COMMANDS: Set[str] = {
    "git", "ls", "dir", "tree", "find", "where", "cat", "type", "head", "tail",
    "grep", "findstr", "wc", "sort", "echo", "date", "whoami", "hostname", "pwd",
    "uname", "systeminfo", "ver",
    "mkdir", "touch", "cp", "copy", "mv", "move", "ren",
    "tar", "unzip", "7z",
}
# Interpreters / package managers / env dumpers: blocked by default.
# Pass via extra_safe only for trusted local sessions.
RISKY_COMMANDS: Set[str] = {
    "python", "python3", "pip", "pip3", "py", "node", "npm", "npx", "yarn", "pnpm",
    "deno", "bun", "env", "set", "printenv",
}

# Dangerous commands always blocked
DENYLIST_COMMANDS: Set[str] = {
    "format", "diskpart", "takeown", "icacls", "cipher",
    "mkfs", "dd", "fdisk", "parted", "shred", "wipefs",
    "regedit", "sfc", "bcdedit", "shutdown", "reboot",
    "halt", "poweroff", "taskkill", "killall",
    "rm", "del", "erase", "rmdir", "rd", "deltree",
    "sudo", "su", "doas", "runas",
    "chmod", "chown", "chgrp", "passwd",
    "curl", "wget", "nc", "ncat", "socat",
    "apt", "apt-get", "brew", "choco", "winget",
    "powershell", "pwsh", "cmd", "cmd.exe",
}

# Dangerous regex patterns
DANGEROUS_PATTERNS = [
    re.compile(r"rm\s+-[a-zA-Z]*r[a-zA-Z]*f\s+", re.I),
    re.compile(r"Remove-Item\s+.*-Recurse\s+-Force", re.I),
    re.compile(r"rmdir\s+/s\s+/q", re.I),
    re.compile(r"format\s+[a-zA-Z]:", re.I),
    re.compile(r"mkfs\.", re.I),
    re.compile(r"dd\s+if=.*of=/dev/", re.I),
    re.compile(r"chmod\s+777", re.I),
    re.compile(r"nc\s+.*-e\s+", re.I),
    re.compile(r"reverse\s+shell", re.I),
    re.compile(r"powershell\s+-[Ee]\s+[A-Za-z0-9+/=]{20,}", re.I),
    re.compile(r"powershell\s+.*-EncodedCommand", re.I),
    re.compile(r"pwsh\s+.*-EncodedCommand", re.I),
    re.compile(r"(^|\s)(-e(nc(odedCommand)?)?)\s+[A-Za-z0-9+/=]{20,}", re.I),
    re.compile(r"FromBase64String|Invoke-Expression|\bIEX\b", re.I),
    re.compile(r";|\|\||&&|\$\(|`|<\(", re.I),
    re.compile(r"(^|\s)\|(\s|$)", re.I),
    re.compile(r">\s*/dev/", re.I),
    re.compile(r"\b(curl|wget)\b.*\|\s*(sh|bash|powershell)", re.I),
]


class CommandSandbox:
    """Command sandbox with allowlist/denylist."""

    def __init__(self, extra_safe=None, extra_deny=None):
        self.safe_commands = SAFE_COMMANDS | (extra_safe or set())
        self.denylist = DENYLIST_COMMANDS | (extra_deny or set())

    def validate_command(self, command: str) -> Tuple[bool, str]:
        if not command or not command.strip():
            return False, "Empty command"
        cmd = command.strip()
        if len(cmd) > 4096:
            return False, "Command too long"
        # Block shell chaining / substitution operators outright. Single
        # commands are executed without a shell (see tools._run_command),
        # so any metachar is an injection attempt. \r is included: Windows
        # PowerShell treats CR as a statement separator, which would otherwise
        # let a second statement hide behind an allowlisted first word.
        if re.search(r"[;&|`$><\r]|(\|\|)|(\$\()|(\n)", cmd):
            # Allow a single plain pipe-free command only; any of these
            # characters indicates chaining/redirection/substitution.
            # '|' alone is also rejected to prevent piping to shells.
            if re.search(r"[;&|`$<>\r\n]|\|\|?|\$\(|`", cmd):
                return False, "Shell metacharacters not allowed (chaining/piping/substitution blocked)"
        try:
            parts = shlex.split(cmd, posix=(os.name != "nt"))
        except ValueError as e:
            return False, f"Unparseable command: {e}"
        if not parts:
            return False, "Empty command"
        first_word = parts[0].split("\\")[-1].split("/")[-1].lower()
        # Strip common executable extensions for comparison
        if first_word.endswith((".exe", ".cmd", ".bat", ".ps1")):
            first_word = first_word.rsplit(".", 1)[0]
        for denied in self.denylist:
            if first_word == denied.lower():
                return False, f"Command '{first_word}' is denied"
        for pattern in DANGEROUS_PATTERNS:
            if pattern.search(cmd):
                return False, "Dangerous pattern detected"
        for safe in self.safe_commands:
            if first_word == safe.lower():
                break
        else:
            return False, f"Command '{first_word}' not in allowlist"
        if ".." in parts or ".." in cmd.split():
            return False, "Path traversal detected"
        return True, "Approved"

    def sanitize_command(self, command: str) -> str:
        if not command:
            return ""
        cmd = command.replace("\x00", "")
        cmd = "".join(c for c in cmd if c.isprintable() or c in ("\t", "\n", "\r"))
        return cmd[:4096].strip()


class WorkspaceBoundary:
    """Enforces workspace boundary for file operations."""

    def __init__(self, workspace_path=None, create: bool = False):
        self.workspace = Path(workspace_path).resolve() if workspace_path else Path.cwd().resolve()
        # Do not touch the filesystem on import/init (test isolation).
        # Directories are created explicitly via set_workspace() or
        # ensure_workspace().
        if create:
            self.ensure_workspace()

    def ensure_workspace(self) -> None:
        try:
            self.workspace.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Could not create workspace {self.workspace}: {e}")
            raise

    def is_within_workspace(self, path: str) -> bool:
        try:
            target = Path(path).resolve()
            return target == self.workspace or self.workspace in target.parents
        except (ValueError, OSError):
            return False

    def validate_path(self, path: str) -> Tuple[bool, str, str]:
        if not path:
            return False, "", "Empty path"
        try:
            target = Path(path).resolve()
        except (ValueError, OSError) as e:
            return False, "", f"Invalid path: {e}"
        if self.is_within_workspace(path):
            return True, str(target), "Within workspace"
        return False, str(target), f"Outside workspace '{self.workspace}'"

    def set_workspace(self, path: str):
        self.workspace = Path(path).resolve()
        self.ensure_workspace()


class InputSanitizer:
    """Sanitize user input before sending to LLM."""

    INJECTION_PATTERNS = [
        re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.I),
        re.compile(r"disregard\s+(all\s+)?prior\s+", re.I),
        re.compile(r"forget\s+(all\s+)?your\s+instructions", re.I),
        re.compile(r"override\s+(your\s+)?system\s+prompt", re.I),
        re.compile(r"you\s+are\s+now\s+", re.I),
        re.compile(r"do\s+anything\s+now", re.I),
        re.compile(r"\bDAN\b.*mode", re.I),
        re.compile(r"jailbreak", re.I),
        re.compile(r"repeat\s+(your\s+)?system\s+prompt", re.I),
        re.compile(r"show\s+me\s+your\s+instructions", re.I),
        re.compile(r"<\|im_start\|>", re.I),
        re.compile(r"<\|im_end\|>", re.I),
    ]

    def detect_injection(self, text: str) -> Tuple[bool, str]:
        for pattern in self.INJECTION_PATTERNS:
            if pattern.search(text):
                return True, f"Potential prompt injection: {pattern.pattern}"
        return False, ""

    def sanitize(self, text: str, strict=False) -> str:
        if not text:
            return ""
        text = text.replace("\x00", "")
        text = "".join(c for c in text if c.isprintable() or c in ("\t", "\n", "\r"))
        if strict:
            # Strict mode actively neutralises injection patterns instead of
            # only logging: replace matched spans with a safe placeholder so
            # the LLM never receives the raw override instruction.
            for pattern in self.INJECTION_PATTERNS:
                text, n = pattern.subn("[blocked-instruction]", text)
                if n:
                    logger.warning(f"Input sanitization (strict): neutralised {n}x {pattern.pattern}")
        return text[:32768]


class APIKeyEncryption:
    """Encrypt/decrypt API keys at rest using Fernet (AES-128-CBC+HMAC).

    Fail-closed: requires the ``cryptography`` package. The legacy weak
    ``enc:`` XOR fallback is decrypt-only for migration and is never used
    for new encryptions.
    """

    def __init__(self, key_file=None):
        self._key_file = Path(key_file) if key_file else Path.home() / ".deepans-code" / ".keystore"
        self._master_key: Optional[bytes] = None
        self._fernet = None
        # Lazy: do not touch disk on import; init on first encrypt/decrypt.

    def _ensure_init(self) -> None:
        if self._fernet is not None and self._master_key is not None:
            return
        self._master_key = self._load_or_create_master_key()
        try:
            from cryptography.fernet import Fernet
        except ImportError as e:
            raise RuntimeError(
                "cryptography package is required for API key encryption. "
                "Install with: pip install cryptography"
            ) from e
        derived = hashlib.pbkdf2_hmac("sha256", self._master_key, b"deepans-code", 200_000)
        self._fernet = Fernet(base64.urlsafe_b64encode(derived[:32]))

    def _load_or_create_master_key(self) -> bytes:
        kf = self._key_file
        if kf.exists():
            data = kf.read_bytes()
            if len(data) < 32:
                raise ValueError("Keystore file is corrupt (too short)")
            self._restrict_keystore_perms()
            return data
        key = secrets.token_bytes(32)
        kf.parent.mkdir(parents=True, exist_ok=True)
        # Write atomically with restrictive perms from the start.
        tmp = kf.with_suffix(".tmp")
        tmp.write_bytes(key)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, kf)
        self._restrict_keystore_perms()
        return key

    def _restrict_keystore_perms(self) -> None:
        from deepans_code.permissions import restrict_file
        restrict_file(self._key_file)

    def encrypt(self, plaintext: str) -> str:
        if not plaintext:
            return ""
        self._ensure_init()
        assert self._fernet is not None
        try:
            encrypted = self._fernet.encrypt(plaintext.encode("utf-8"))
            return "aes:" + encrypted.decode("ascii")
        except Exception as e:
            logger.error(f"API key encryption failed: {e}")
            raise

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext:
            return ciphertext
        if ciphertext.startswith("aes:"):
            self._ensure_init()
            assert self._fernet is not None
            try:
                decrypted = self._fernet.decrypt(ciphertext[4:].encode("ascii"))
                return decrypted.decode("utf-8")
            except Exception as e:
                logger.error(f"API key decryption failed: {e}")
                raise ValueError("Failed to decrypt API key") from e
        if ciphertext.startswith("enc:"):
            # Legacy weak XOR format: decrypt-only for migration.
            logger.warning("Decrypting legacy weak-format key; re-encrypting to AES on next save")
            if self._master_key is None:
                self._master_key = self._load_or_create_master_key()
            try:
                encrypted = base64.b64decode(ciphertext[4:])
                key_hash = hashlib.sha256(self._master_key).digest()
                decrypted = bytes(
                    b ^ key_hash[i % len(key_hash)]
                    for i, b in enumerate(encrypted)
                )
                return decrypted.decode("utf-8")
            except Exception as e:
                logger.error(f"Legacy key decryption failed: {e}")
                raise ValueError("Failed to decrypt legacy API key") from e
        return ciphertext


class RateLimiter:
    """Token bucket rate limiter for API calls."""

    def __init__(self, max_requests: int = 20, window_seconds: int = 60):
        self._max_requests = max_requests
        self._window = window_seconds
        self._requests: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def allow(self, key: str = "default") -> bool:
        with self._lock:
            now = time.time()
            self._requests[key] = [t for t in self._requests[key] if now - t < self._window]
            if len(self._requests[key]) < self._max_requests:
                self._requests[key].append(now)
                return True
            return False

    def remaining(self, key: str = "default") -> int:
        with self._lock:
            now = time.time()
            self._requests[key] = [t for t in self._requests[key] if now - t < self._window]
            return max(0, self._max_requests - len(self._requests[key]))

    def reset(self, key: str = "default"):
        with self._lock:
            self._requests.pop(key, None)


class CSRFProtection:
    """CSRF token generation and validation for API endpoints."""

    def __init__(self):
        self._tokens: Dict[str, Tuple[str, float]] = {}
        self._lock = threading.Lock()

    def generate_token(self, session_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            # Evict expired entries + cap size to prevent memory leak.
            expired = [k for k, (_, ts) in self._tokens.items() if now - ts > 3600]
            for k in expired:
                self._tokens.pop(k, None)
            if len(self._tokens) > 1000:
                oldest = sorted(self._tokens.items(), key=lambda kv: kv[1][1])[: len(self._tokens) - 1000]
                for k, _ in oldest:
                    self._tokens.pop(k, None)
            self._tokens[session_id] = (token, now)
        return token

    def validate_token(self, session_id: str, token: str, max_age: int = 3600) -> bool:
        if not session_id or not token:
            return False
        with self._lock:
            entry = self._tokens.get(session_id)
            if not entry:
                return False
            expected, created = entry
            if (time.time() - created) >= max_age:
                self._tokens.pop(session_id, None)
                return False
            if not hmac.compare_digest(expected, token):
                return False
            return True

    def invalidate(self, session_id: str):
        with self._lock:
            self._tokens.pop(session_id, None)


# Global instances
sandbox = CommandSandbox()
workspace = WorkspaceBoundary()
sanitizer = InputSanitizer()
rate_limiter = RateLimiter()
csrf_protection = CSRFProtection()
