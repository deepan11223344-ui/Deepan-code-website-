"""Backward-compat shim.

Single source of truth is ``pyproject.toml`` (PEP 517). This file exists
only for old tooling that still invokes ``setup.py`` directly, and for the
packaging guard test (``tests/test_hardening.py::TestPackaging``) which
asserts the literals below. Do NOT add new metadata here — edit
``pyproject.toml`` instead.
"""

from setuptools import setup, find_packages

setup(
    name="deepans-code",
    version="3.0.0",
    description="Terminal CLI based AI Agent for Windows PowerShell & Linux Terminals acting like Claude Code, OpenCode, and Codex.",
    author="Deepan",
    packages=find_packages(include=["deepans_code*"]),
    install_requires=[
        "rich>=13.0.0",
        "prompt_toolkit>=3.0.0",
        "httpx>=0.24.0",
        "pydantic>=2.0.0",
        "websockets>=12.0",
        "cryptography>=41.0.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-cov>=4.0.0",
            "pytest-asyncio>=0.21.0",
            "pytest-mock>=3.10.0",
            "flake8>=6.0.0",
            "black>=23.0.0",
            "isort>=5.0.0",
            "mypy>=1.0.0",
            "psutil>=5.9.0",
        ],
        "full": [
            "cryptography>=41.0.0",
            "psutil>=5.9.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "deepans-code=deepans_code.cli:run_cli",
        ],
    },
    python_requires=">=3.10",
)
