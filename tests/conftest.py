"""
Global test isolation for DeepanCode.

1. HOME redirect at IMPORT time (before any test module imports
   deepans_code submodules that mkdir at import: metrics, monitoring,
   token_usage). All import-time and default-path filesystem writes land
   in an isolated temp HOME that is removed at session end.
2. Autouse per-test restore of process-global mutable state:
   tools workspace + config_mgr in-memory config.
"""

import atexit
import copy
import os
import shutil
import tempfile
from pathlib import Path

import pytest

_ISOLATED_HOME = Path(tempfile.mkdtemp(prefix="deepans-test-home-"))
os.environ["HOME"] = str(_ISOLATED_HOME)
os.environ["USERPROFILE"] = str(_ISOLATED_HOME)  # Windows expanduser


def _cleanup_home():
    shutil.rmtree(_ISOLATED_HOME, ignore_errors=True)


atexit.register(_cleanup_home)


@pytest.fixture(autouse=True)
def _restore_global_state():
    """Snapshot/restore workspace + in-memory config around every test."""
    ws_path = None
    cfg_snapshot = None
    try:
        from deepans_code import tools as _tools
        ws_path = _tools.workspace.workspace
    except Exception:
        pass
    try:
        from deepans_code.config import get_config as _get_config
        cfg_snapshot = copy.deepcopy(_get_config().config)
    except Exception:
        pass
    yield
    try:
        from deepans_code import tools as _tools
        if ws_path is not None:
            _tools.workspace.workspace = Path(ws_path)
    except Exception:
        pass
    try:
        from deepans_code.config import get_config as _get_config
        if cfg_snapshot is not None:
            _get_config().config.clear()
            _get_config().config.update(cfg_snapshot)
    except Exception:
        pass
