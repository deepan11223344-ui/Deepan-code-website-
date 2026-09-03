"""One-shot refactor: split handle_slash_command elif chain into registry functions.

Run once:  python scripts/split_cli.py
Idempotent guard: exits if cli.py already has COMMAND_HANDLERS with /model.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "deepans_code" / "cli.py"

CANON = {
    "/model": "model", "/connectors": "connect", "/connector": "connect",
    "/connect": "connect", "/effort": "effort", "/mode": "mode",
    "/themes": "themes", "/agents": "agents", "/mcp": "mcp",
    "/skills": "skills", "/metrics": "metrics", "/history": "history",
    "/export": "export", "/cache": "cache", "/plugins": "plugins",
    "/switch": "switch",
}

text = CLI.read_text(encoding="utf-8")
if 'COMMAND_HANDLERS = {' in text and '"/model"' in text.split('COMMAND_HANDLERS = {')[1][:500]:
    print("Already split. Exiting.")
    raise SystemExit(0)

lines = text.splitlines()
start = next(i for i, l in enumerate(lines) if l.startswith("def handle_slash_command"))
end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("def ") and "handle_slash" not in lines[i])

block = lines[start:end]
# find branch headers within block (relative indices)
hdr = [i for i, l in enumerate(block) if l.strip().startswith("if cmd") or l.strip().startswith("elif cmd")]
print(f"Found {len(hdr)} branches")

funcs = []
for bi, hi in enumerate(hdr):
    header = block[hi].strip()
    cmds = re.findall(r'"([^"]+)"', header)
    # skip already-migrated simple commands (handled by cli_commands registry)
    if all(c in ("/exit", "/quit", "exit", "quit", "/esc", "/help", "/think", "/status", "/clear") for c in cmds):
        continue
    # canonical function name from first mappable cmd
    fname = None
    for c in cmds:
        if c in CANON:
            fname = "_cmd_" + CANON[c]
            break
    if fname is None:
        slug = re.sub(r"\W+", "", cmds[0]) if cmds else f"branch{bi}"
        fname = "_cmd_" + slug
    # body = lines until next header (exclusive)
    nxt = hdr[bi + 1] if bi + 1 < len(hdr) else len(block)
    body = block[hi + 1:nxt]
    # drop trailing blank lines; body lines have >=8-space indent; dedent 4
    while body and not body[-1].strip():
        body.pop()
    dedented = []
    for bl in body:
        if bl.startswith("        "):
            dedented.append("    " + bl[8:])
        elif bl.strip() == "":
            dedented.append("")
        else:
            dedented.append("    " + bl.strip())
    # ensure returns True at end if not already returning
    if not any("return True" in bl for bl in dedented[-3:]):
        dedented.append("    return True")
    funcs.append((fname, cmds, dedented))

print("Extracting:", [f for f, _, _ in funcs])

# Build new code: functions + registry + thin dispatcher
out_funcs = ["\n\n# ============================================================================",
             "# Slash-command handlers (split from handle_slash_command registry migration).",
             "# Each handler: (parts, theme) -> bool. No elif chain; see COMMAND_HANDLERS.",
             "# ============================================================================"]
for fname, cmds, dedented in funcs:
    out_funcs.append("")
    out_funcs.append("")
    out_funcs.append(f"def {fname}(parts, theme):")
    out_funcs.extend(dedented)

out_funcs.append("")
out_funcs.append("")
out_funcs.append("COMMAND_HANDLERS = {")
for fname, cmds, _ in funcs:
    for c in cmds:
        out_funcs.append(f'    "{c.lower()}": {fname},')
out_funcs.append("}")
out_funcs.append("")

dispatcher = [
    "",
    "",
    "def handle_slash_command(cmd_line):",
    '    """Dispatch slash commands via COMMAND_HANDLERS registry (no elif chain).',
    "",
    "    Handlers live as module-level _cmd_* functions above. Simple commands",
    "    (/help, /clear, /status, /think, /exit, /esc) are served first by",
    "    deepans_code.cli_commands; everything else resolves here.",
    '    """',
    "    from deepans_code.cli_commands import dispatch as _dispatch",
    "",
    "    parts = cmd_line.strip().split()",
    "    if not parts:",
    "        return False",
    "    cmd = parts[0].lower()",
    "    theme = get_theme()",
    '    ctx = {"console": console, "theme": theme, "config_mgr": config_mgr}',
    "    try:",
    "        handled = _dispatch(cmd, parts, ctx)",
    "    except SystemExit:",
    "        raise",
    "    except Exception as e:",
    "        console.print(f\"[red]Command error: {e}[/red]\")",
    "        return True",
    "    if handled:",
    "        return True",
    "    handler = COMMAND_HANDLERS.get(cmd)",
    "    if handler is None:",
    "        return False",
    "    try:",
    "        return bool(handler(parts, theme))",
    "    except SystemExit:",
    "        raise",
    "    except Exception as e:",
    "        console.print(f\"[red]Command error: {e}[/red]\")",
    "        return True",
    "",
]

new_lines = lines[:start] + dispatcher + out_funcs + lines[end:]
CLI.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
print(f"Wrote {CLI} ({len(funcs)} handlers extracted)")
