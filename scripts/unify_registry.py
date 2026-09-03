"""One-shot: unify slash-command registry into deepans_code.cli_commands.

- Rewrites `def _cmd_*(parts, theme):` in cli.py to `(parts, ctx)` with
  `theme = ctx["theme"]` prologue (console/config_mgr resolve as before via
  module globals, also present in ctx).
- Registers every cli.py handler into cli_commands.COMMAND_HANDLERS.
- handle_slash_command becomes dispatch-only via cli_commands.
- SLASH_COMMANDS derived from the single registry (+ /search flow).
- Removes dead `return False` after _cmd_switch.
Run once: python scripts/unify_registry.py
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "deepans_code" / "cli.py"

text = CLI.read_text(encoding="utf-8")
if "def _cmd_model(parts, ctx):" in text:
    print("Already unified. Exiting.")
    raise SystemExit(0)

# 1. Signature rewrite for all module-level handlers.
text, n = re.subn(
    r"^def (_cmd_\w+)\(parts, theme\):$",
    r"def \1(parts, ctx):\n    theme = ctx[\"theme\"]",
    text,
    flags=re.M,
)
print(f"Rewrote {n} handler signatures")

# 2. Drop dead return after _cmd_switch.
text = text.replace(
    "    console.print()\n    return True\n\n    return False\n\n\nCOMMAND_HANDLERS",
    "    console.print()\n    return True\n\n\nCOMMAND_HANDLERS",
)

lines = text.splitlines()
start = next(i for i, l in enumerate(lines) if l.startswith("COMMAND_HANDLERS = {"))
# dict ends at first line that is exactly "}"
end = next(i for i in range(start, len(lines)) if lines[i].strip() == "}")
entries = [l.strip().rstrip(",") for l in lines[start + 1:end] if l.strip()]
pairs = []
for e in entries:
    m = re.match(r'"([^"]+)"\s*:\s*(\w+)', e)
    if m:
        pairs.append((m.group(1), m.group(2)))
print(f"Found {len(pairs)} registry pairs")

registration = ["", "", "# Register every handler into the single cli_commands registry.", "from deepans_code.cli_commands import register as _register_command"]
seen = set()
for cmd, fn in pairs:
    registration.append(f'_register_command("{cmd}", {fn})')
registration.append("")

# 3. Replace local dict + dispatcher with alias + thin dispatch.
handler_src = "\n".join(lines[start:end + 1])
new_tail = "\n".join(registration)
new_tail += '''
COMMAND_HANDLERS = __import__("deepans_code.cli_commands", fromlist=["COMMAND_HANDLERS"]).COMMAND_HANDLERS
'''
text = text.replace(handler_src, new_tail.strip("\n"))

# 4. Thin dispatcher: single-registry lookup.
old_disp_start = text.index("def handle_slash_command(cmd_line):")
old_disp_end = text.index("def _cmd_model(parts, ctx):")
new_disp = '''def handle_slash_command(cmd_line):
    """Dispatch slash commands via the single cli_commands registry.

    No elif chain and no secondary dict: COMMAND_HANDLERS is an alias of
    deepans_code.cli_commands.COMMAND_HANDLERS. Add commands only via
    cli_commands.register().
    """
    from deepans_code.cli_commands import dispatch as _dispatch

    parts = cmd_line.strip().split()
    if not parts:
        return False
    cmd = parts[0].lower()
    ctx = {"console": console, "theme": get_theme(), "config_mgr": config_mgr}
    try:
        handled = _dispatch(cmd, parts, ctx)
    except SystemExit:
        raise
    except Exception as e:
        console.print(f"[red]Command error: {e}[/red]")
        return True
    if handled:
        return True
    return False


'''
text = text[:old_disp_start] + new_disp + text[old_disp_end:]

# 5. SLASH_COMMANDS derived from registry (+ /search inline flow).
old_slash_start = text.index("SLASH_COMMANDS = [")
old_slash_end = text.index("]", old_slash_start) + 1
new_slash = ("# Canonical command list: every registered command plus the inline\n"
             "# /search flow (handled in run_cli, not a slash-command handler).\n"
             "def _slash_commands():\n"
             "    from deepans_code.cli_commands import COMMAND_HANDLERS as _H\n"
             "    return sorted(set(_H) | {\"/search\"})\n"
             "\n"
             "\n"
             "SLASH_COMMANDS = _slash_commands()")
text = text[:old_slash_start] + new_slash + text[old_slash_end:]

CLI.write_text(text + "\n" if not text.endswith("\n") else text, encoding="utf-8")
print("Unified registry written")
