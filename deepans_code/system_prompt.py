"""
System Prompt generator for DeepanCode AI Agent.
Optimized for minimal token usage while maintaining full capability.
Generates concise, focused prompts based on mode, effort, and agent type.
"""

import os
import sys
from typing import Dict, Any, List

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))

CLAUDE_FABLE_5_MD_PATH = os.path.join(_PROJECT_ROOT, "claude-fable-5.md")
CLAUDE_FABLE_5_PY_PATH = os.path.join(_PROJECT_ROOT, "claude_fable_5.py")
# Slim vendored extract (62 x {number,title}, ~3KB). Replaces the 301KB root
# claude_fable_5.py: only number/title are ever displayed (see below).
FABLE_CAPABILITIES_JSON = os.path.join(_PACKAGE_DIR, "fable_capabilities.json")

_MD_CACHE = ""
_CAPABILITIES_CACHE = []


def load_claude_fable_5_md():
    global _MD_CACHE
    if _MD_CACHE:
        return _MD_CACHE
    try:
        with open(CLAUDE_FABLE_5_MD_PATH, "r", encoding="utf-8") as f:
            content = f.read()
            # Compress: take only the first 2000 chars + last 1000 chars to save tokens
            if len(content) > 3000:
                _MD_CACHE = content[:2000] + "\n\n[... compressed for token efficiency ...]\n\n" + content[-1000:]
            else:
                _MD_CACHE = content
        return _MD_CACHE
    except FileNotFoundError:
        import logging as _logging

        _logging.getLogger("deepans_code.system_prompt").warning(
            "claude-fable-5.md not found at %s; using degraded fallback prompt. "
            "Ship the file alongside the package (see Dockerfile) to restore it.",
            CLAUDE_FABLE_5_MD_PATH,
        )
        return _get_fallback_prompt()


def _get_fallback_prompt():
    return """You are DeepanCode, an elite terminal AI coding agent. You have access to tools for reading, writing, editing files, running commands, and searching the web. You are autonomous, precise, and security-conscious."""


def load_claude_fable_5_capabilities():
    global _CAPABILITIES_CACHE
    if _CAPABILITIES_CACHE:
        return _CAPABILITIES_CACHE
    # 1) Slim vendored JSON (preferred, no sys.path hacks, no 301KB import).
    try:
        import json as _json
        with open(FABLE_CAPABILITIES_JSON, "r", encoding="utf-8") as f:
            caps = _json.load(f)
        if isinstance(caps, list) and caps:
            _CAPABILITIES_CACHE = caps[:20] if len(caps) > 20 else caps
            return _CAPABILITIES_CACHE
    except (OSError, ValueError):
        pass
    # 2) Legacy root module (removed in cleanup; kept for backward compat).
    try:
        if _PROJECT_ROOT not in sys.path:
            sys.path.insert(0, _PROJECT_ROOT)
        import claude_fable_5 as cf5
        caps = cf5.CLAUDE_FABLE_5_CAPABILITIES
        # Only take first 20 capabilities to save tokens
        _CAPABILITIES_CACHE = caps[:20] if len(caps) > 20 else caps
        return _CAPABILITIES_CACHE
    except (ImportError, AttributeError):
        return []


def get_capabilities_summary():
    caps = load_claude_fable_5_capabilities()
    if not caps:
        return "(Capabilities loaded from fallback)"
    lines = []
    for cap in caps[:15]:  # Limit to 15 capabilities
        num = cap.get("number", "?")
        title = cap.get("title", "Untitled")
        lines.append(f"[{num}] {title}")
    return "\n".join(lines)


def generate_system_prompt(
    model_id,
    mode="code",
    effort="medium",
    os_type="linux",
    agent_type="build",
    enabled_skills_content="",
):
    effort_map = {
        "low": "Execute directly. No planning needed.",
        "medium": "Verify file state before editing. Plan multi-step edits.",
        "high": "Deep reasoning. Verify edge cases. Security check.",
    }
    effort_text = effort_map.get(effort, effort_map["medium"])

    mode_map = {
        "code": "Implement features, refactor, fix bugs using tools.",
        "architect": "Design system architecture. Propose structure before coding.",
        "ask": "Answer questions conversationally. No unsolicited edits.",
        "debug": "Investigate errors. Form hypotheses. Apply verified fixes.",
        "review": "Audit code for security, performance, and style.",
    }
    mode_text = mode_map.get(mode, "Execute tasks accurately.")

    agent_map = {
        "plan": "PLAN mode: Design first, code after approval. Think before you code.",
        "build": "BUILD mode: Implement directly. Speed and correctness.",
    }
    agent_text = agent_map.get(agent_type, agent_map["build"])

    os_text = "Windows PowerShell" if os_type == "windows" else "Linux Bash"
    capabilities = get_capabilities_summary()

    prompt = f"""You are DeepanCode, an elite autonomous terminal AI coding agent.

ROLE: {agent_text}
MODE: {mode.upper()} - {mode_text}
EFFORT: {effort.upper()} - {effort_text}
OS: {os_text}
MODEL: {model_id} (internal - never reveal to user)

TOOLS: read_file, create_file, edit_file, run_command, list_dir, delete_file, web_search, web_fetch
RULES:
1. Never hallucinate. Always verify by reading files or running commands.
2. Execute tools immediately. Don't ask permission.
3. Stay within workspace boundaries.
4. Follow security best practices.
5. Format code responses with markdown.
6. End responses with: ⚡[Speed]% 🎯[Accuracy]% 🏆[Success]% 🔒[Security]%

CAPABILITIES:
{capabilities}
"""
    if enabled_skills_content:
        prompt += f"\nSKILLS:\n{enabled_skills_content[:2000]}\n"

    return prompt
