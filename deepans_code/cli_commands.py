"""
Split command dispatcher for DeepanCode CLI.

Replaces the 700-line `handle_slash_command` if/elif chain with a
registry: COMMAND_HANDLERS maps command name -> handler function.

Each handler signature: handler(parts: list[str], ctx: dict) -> bool | None
Return True if handled. ctx carries console/theme/config to avoid
circular imports (cli.py builds ctx and delegates here).

New commands must be added as a function + registry entry, never as
another elif branch.
"""

from __future__ import annotations

from typing import Callable, Dict, List


def _cmd_exit(parts, ctx) -> bool:
    ctx["console"].print("[yellow]Goodbye![/yellow]")
    raise SystemExit(0)


def _cmd_esc(parts, ctx) -> bool:
    ctx["console"].print("[yellow]Task cancelled. Returning to prompt.[/yellow]")
    return True


def _cmd_help(parts, ctx) -> bool:
    from rich.table import Table

    console, theme = ctx["console"], ctx["theme"]
    console.print()
    console.print(f"[bold {theme['primary']}]Available Commands[/bold {theme['primary']}]")
    console.print()
    table = Table(show_header=True, header_style=f"bold {theme['primary']}", box=None, padding=(0, 2))
    table.add_column("Command", style=theme["primary"], no_wrap=True)
    table.add_column("Description", style="white")
    for cmd, desc in sorted(COMMAND_HELP.items()):
        table.add_row(cmd, desc)
    console.print(table)
    console.print()
    return True


def _cmd_clear(parts, ctx) -> bool:
    from deepans_code.agent import get_agent

    get_agent().reset_conversation()
    ctx["console"].print("[green]Conversation cleared.[/green]")
    return True


def _cmd_status(parts, ctx) -> bool:
    from deepans_code.agent import get_agent

    console = ctx["console"]
    usage = get_agent().get_token_usage()
    console.print(f"[cyan]Model:[/cyan] {usage.get('model_id')} ({usage.get('provider_id')})")
    console.print(f"[cyan]Tokens:[/cyan] {usage.get('total_used')}/{usage.get('context_window')} ({usage.get('percentage', 0):.1f}%)")
    return True


def _cmd_think(parts, ctx) -> bool:
    console, config_mgr = ctx["console"], ctx["config_mgr"]
    if len(parts) > 1 and parts[1].lower() in ("on", "off"):
        config_mgr.set("thinking", parts[1].lower() == "on")
        console.print(f"[green]Thinking display: {parts[1].lower()}[/green]")
    else:
        cur = config_mgr.get("thinking", True)
        console.print(f"[dim]Thinking display is {'on' if cur else 'off'}. Use /think on|off[/dim]")
    return True


COMMAND_HELP: Dict[str, str] = {
    "/model": "List all free LLM models",
    "/model <#>": "Switch to model by number",
    "/agents": "Select agent type (Plan/Build)",
    "/connect": "Setup API key (interactive menu)",
    "/connect <provider> <key>": "Save API key directly",
    "/effort": "Set thinking depth (interactive menu)",
    "/mode": "Switch mode (interactive menu)",
    "/themes": "Change color theme (interactive menu)",
    "/think <on|off>": "Toggle thinking display",
    "/mcp <list|add|rm|toggle>": "Manage MCP servers",
    "/skills [list|import|enable|disable|remove|show]": "Manage agent skills",
    "/status": "Show session info",
    "/metrics": "Show performance dashboard",
    "/history": "Browse conversation history",
    "/export [md|json]": "Export conversation",
    "/cache [stats|clear]": "Cache management",
    "/plugins": "List loaded plugins",
    "/switch": "Quick switch provider (auto-fallback)",
    "/clear": "Clear conversation",
    "/esc": "Stop/Cancel current input",
    "/help": "Show this help",
}

# Registry: every key must be a canonical lowercase command.
COMMAND_HANDLERS: Dict[str, Callable] = {
    "/exit": _cmd_exit,
    "/quit": _cmd_exit,
    "exit": _cmd_exit,
    "quit": _cmd_exit,
    "/esc": _cmd_esc,
    "/help": _cmd_help,
    "/clear": _cmd_clear,
    "/status": _cmd_status,
    "/think": _cmd_think,
}


def dispatch(cmd: str, parts: List[str], ctx: dict) -> bool | None:
    """Dispatch a slash command. Returns True if handled, None if unknown."""
    handler = COMMAND_HANDLERS.get(cmd.lower())
    if handler is None:
        return None
    return handler(parts, ctx)


def register(cmd: str, handler: Callable, help_text: str = "") -> None:
    """Extension point for plugins: register a new slash command."""
    COMMAND_HANDLERS[cmd.lower()] = handler
    if help_text:
        COMMAND_HELP[cmd] = help_text
