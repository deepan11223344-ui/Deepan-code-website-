"""
Logging configuration for DeepanCode.
Replaces print() with proper structured logging.
"""

import os
import logging
import logging.handlers
import re
from pathlib import Path

LOG_DIR = Path.home() / ".deepans-code" / "logs"
LOG_FILE = LOG_DIR / "deepans_code.log"

# Patterns redacted from every log record (console + file).
REDACT_PATTERNS = [
    re.compile(r"sk-or-[A-Za-z0-9_\-]{4,}"),
    re.compile(r"oc_[A-Za-z0-9_\-]{4,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9_\-\.~\+/=]{4,}"),
    re.compile(r'(?i)("apiKey"\s*:\s*")[^"]*(")'),
    re.compile(r"(?i)(api[_-]?key\s*=\s*)[^\s,;]+"),
    # snake/kebab JSON + generic secret fields ("api_key": "...",
    # "password": "...", "secret": "...", "access_token": "...").
    re.compile(r'(?i)("(?:api[_-]?key|password|passwd|secret|access[_-]?token|auth[_-]?token)"\s*:\s*")[^"]*(")'),
]


def redact(text: str) -> str:
    if not isinstance(text, str):
        text = str(text)
    red = text
    red = REDACT_PATTERNS[0].sub("sk-or-***REDACTED***", red)
    red = REDACT_PATTERNS[1].sub("oc_***REDACTED***", red)
    red = REDACT_PATTERNS[2].sub("sk-***REDACTED***", red)
    red = REDACT_PATTERNS[3].sub(r"\1***REDACTED***", red)
    red = REDACT_PATTERNS[4].sub(r"\1***REDACTED***\2", red)
    red = REDACT_PATTERNS[5].sub(r"\1***REDACTED***", red)
    red = REDACT_PATTERNS[6].sub(r"\1***REDACTED***\2", red)
    return red


class RedactingFormatter(logging.Formatter):
    """Formatter that redacts secrets from messages and args."""

    def format(self, record: logging.LogRecord) -> str:
        try:
            if record.args:
                if isinstance(record.args, tuple):
                    record.args = tuple(redact(str(a)) for a in record.args)
                else:
                    record.args = redact(record.args)
            record.msg = redact(record.getMessage())
            record.args = ()
        except Exception:
            pass
        return super().format(record)


def setup_logging(level=logging.INFO, log_to_file=True):
    from deepans_code.permissions import restrict_dir, restrict_file
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    restrict_dir(LOG_DIR)
    root = logging.getLogger()
    root.setLevel(level)
    formatter = RedactingFormatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)
    if log_to_file:
        file_handler = logging.handlers.RotatingFileHandler(
            str(LOG_FILE), maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
        try:
            if LOG_FILE.exists():
                restrict_file(LOG_FILE)
        except Exception:
            pass
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return root
