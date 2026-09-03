"""
Web database accessor. One Database bound to DEEPANCODE_WEB_DB
(default ~/.deepans-code/web.db), separate from the CLI database file
so CLI rows (user_id NULL) and web rows never collide.
"""

import os
from pathlib import Path

from deepans_code.database import Database

_web_db = None


def web_db_path() -> Path:
    raw = os.environ.get("DEEPANCODE_WEB_DB", "")
    if raw:
        return Path(raw)
    return Path.home() / ".deepans-code" / "web.db"


def get_web_db() -> Database:
    global _web_db
    if _web_db is None:
        _web_db = Database(db_path=web_db_path())
    return _web_db


def reset_web_db() -> None:
    """Tests only: drop the cached handle so a new path takes effect."""
    global _web_db
    _web_db = None
