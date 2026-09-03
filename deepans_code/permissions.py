"""
Cross-platform file permission hardening for DeepanCode secrets.

POSIX: 0o600 files / 0o700 dirs.
Windows: best-effort `icacls /inheritance:r /grant:r <user>:(R,W)` so only
the current user can read secrets (DB, config, keystore, logs).
All helpers are best-effort and never raise — hardening must not break
the app when ACL tools are unavailable (CI containers, etc.).
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger("deepans_code.permissions")


def _windows_lockdown(path: Path, read_write: bool = True) -> bool:
    if os.name != "nt":
        return False
    try:
        user = os.environ.get("USERNAME", "")
        if not user:
            return False
        perm = "(R,W)" if read_write else "(R)"
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:{perm}"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        return True
    except Exception as e:
        logger.warning(f"Windows ACL lockdown failed for {path}: {e}")
        return False


def restrict_file(path: str | Path) -> None:
    """Restrict a secret-bearing file (DB, config, keystore, skill state, logs)."""
    p = Path(path)
    if not p.exists():
        return
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    _windows_lockdown(p, read_write=True)


def restrict_dir(path: str | Path) -> None:
    """Restrict a secret-bearing directory (0o700 + Windows ACL)."""
    p = Path(path)
    if not p.exists():
        return
    try:
        os.chmod(p, 0o700)
    except OSError:
        pass
    _windows_lockdown(p, read_write=True)


def atomic_write(path: str | Path, data: bytes, mode: int = 0o600) -> None:
    """Write bytes atomically with restrictive perms from the start."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    # Never follow a pre-planted symlink at the tmp location.
    try:
        if tmp.is_symlink() or tmp.exists():
            tmp.unlink()
    except OSError:
        pass
    tmp.write_bytes(data)
    try:
        os.chmod(tmp, mode)
    except OSError:
        pass
    os.replace(tmp, p)
    restrict_file(p)
