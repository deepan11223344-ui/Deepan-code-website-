"""
Terminal CLI User Interface for DeepanCode.
Built with Rich and Prompt Toolkit for an elite OpenCode / Claude Code terminal experience.
Supports Windows PowerShell, CMD, and Linux/macOS Bash & Zsh.
"""

import os
import sys
import io
import time
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.table import Table
from rich.syntax import Syntax
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

# Fix Windows encoding for special characters (reconfigure only; never
# replace sys.stdout so pipes/redirection keep working).
if os.name == "nt":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.document import Document
    PROMPT_TOOLKIT_AVAILABLE = True
except ImportError:
    PROMPT_TOOLKIT_AVAILABLE = False

from deepans_code import __version__, __app_name__
from deepans_code.config import config_mgr
from deepans_code.models import get_all_models, get_model_info, PROVIDERS
from deepans_code.agent import get_agent
from deepans_code.mcp_manager import mcp_mgr

# Backwards-compat alias: lazily resolves to the shared Agent instance.
# `from deepans_code.cli import agent_instance` keeps working.
def __getattr__(name):
    if name == "agent_instance":
        return get_agent()
    raise AttributeError(name)
console = Console()

# ============================================================================
# Custom Slash Command Completer with Arrow Navigation
# ============================================================================

if PROMPT_TOOLKIT_AVAILABLE:
    class SlashCommandCompleter(Completer):
        """Shows all / commands when user types /, filters as they type."""

        def __init__(self, commands):
            self.commands = commands

        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            if not text.startswith("/"):
                return
            prefix = text.lower()
            for cmd in self.commands:
                if cmd.startswith(prefix):
                    yield Completion(
                        cmd,
                        start_position=-len(text),
                        display=cmd,
                    )

    KB = KeyBindings()

    @KB.add("down")
    def _(event):
        buf = event.app.current_buffer
        if buf.complete_state:
            buf.complete_next()
        else:
            buf.start_completion()

    @KB.add("up")
    def _(event):
        buf = event.app.current_buffer
        if buf.complete_state:
            buf.complete_previous()
        else:
            buf.start_completion()

    @KB.add("tab")
    def _(event):
        event.app.current_buffer.start_completion(select_first=True)

else:
    class SlashCommandCompleter:
        def __init__(self, commands):
            self.commands = commands
        def get_completions(self, document, complete_event):
            return
    KB = None

# Theme definitions
THEMES = {
    "default": {"name": "Default", "primary": "cyan", "accent": "green", "border": "cyan", "font": "bold cyan"},
    "dark": {"name": "Dark", "primary": "bright_black", "accent": "bright_blue", "border": "bright_black", "font": "bold bright_black"},
    "light": {"name": "Light", "primary": "blue", "accent": "green", "border": "blue", "font": "bold blue"},
    "matrix": {"name": "Matrix", "primary": "green", "accent": "bright_green", "border": "green", "font": "bold green"},
    "purple": {"name": "Purple", "primary": "magenta", "accent": "bright_magenta", "border": "magenta", "font": "bold magenta"},
    "fire": {"name": "Fire", "primary": "red", "accent": "yellow", "border": "red", "font": "bold red"},
    "ocean": {"name": "Ocean", "primary": "cyan", "accent": "blue", "border": "bright_blue", "font": "bold blue"},
    "neon": {"name": "Neon", "primary": "bright_green", "accent": "bright_magenta", "border": "bright_green", "font": "bold bright_green"},
    "sunset": {"name": "Sunset", "primary": "yellow", "accent": "red", "border": "yellow", "font": "bold yellow"},
    "royal": {"name": "Royal", "primary": "bright_blue", "accent": "bright_cyan", "border": "bright_blue", "font": "bold bright_blue"},
    "crimson": {"name": "Crimson", "primary": "bright_red", "accent": "red", "border": "bright_red", "font": "bold bright_red"},
    "emerald": {"name": "Emerald", "primary": "bright_green", "accent": "cyan", "border": "bright_green", "font": "bold bright_green"},
    "violet": {"name": "Violet", "primary": "bright_magenta", "accent": "bright_cyan", "border": "bright_magenta", "font": "bold bright_magenta"},
    "amber": {"name": "Amber", "primary": "yellow", "accent": "bright_yellow", "border": "yellow", "font": "bold yellow"},
    "teal": {"name": "Teal", "primary": "cyan", "accent": "bright_cyan", "border": "cyan", "font": "bold cyan"},
    "rose": {"name": "Rose", "primary": "bright_red", "accent": "magenta", "border": "bright_red", "font": "bold bright_red"},
    "gold": {"name": "Gold", "primary": "bright_yellow", "accent": "yellow", "border": "bright_yellow", "font": "bold bright_yellow"},
    "arctic": {"name": "Arctic", "primary": "bright_cyan", "accent": "bright_blue", "border": "bright_cyan", "font": "bold bright_cyan"},
    "lime": {"name": "Lime", "primary": "green", "accent": "bright_green", "border": "green", "font": "bold green"},
    "midnight": {"name": "Midnight", "primary": "bright_black", "accent": "bright_magenta", "border": "bright_black", "font": "bold bright_black"},
    "opencode": {"name": "OpenCode", "primary": "bright_green", "accent": "bright_cyan", "border": "bright_green", "font": "bold bright_green"},
    "opencode-dark": {"name": "OpenCode Dark", "primary": "green", "accent": "cyan", "border": "green", "font": "bold green"},
    "opencode-light": {"name": "OpenCode Light", "primary": "blue", "accent": "bright_blue", "border": "blue", "font": "bold blue"},
    "opencode-zen": {"name": "OpenCode Zen", "primary": "bright_cyan", "accent": "bright_green", "border": "bright_cyan", "font": "bold bright_cyan"},
    "claude": {"name": "Claude", "primary": "bright_red", "accent": "yellow", "border": "bright_red", "font": "bold bright_red"},
    "claude-dark": {"name": "Claude Dark", "primary": "yellow", "accent": "bright_yellow", "border": "yellow", "font": "bold yellow"},
    "claude-light": {"name": "Claude Light", "primary": "bright_red", "accent": "red", "border": "bright_red", "font": "bold bright_red"},
    "claude-midnight": {"name": "Claude Midnight", "primary": "magenta", "accent": "bright_magenta", "border": "magenta", "font": "bold magenta"},
}

# Canonical command list: every registered command plus the inline
# /search flow (handled in run_cli, not a slash-command handler).
# NOTE: SLASH_COMMANDS is (re)built AFTER handler registration below, so it
# always covers the full registry. _slash_commands() reads it live.
def _slash_commands():
    from deepans_code.cli_commands import COMMAND_HANDLERS as _H
    return sorted(set(_H) | {"/search"})


SLASH_COMMANDS = _slash_commands()

# Initialize completer after SLASH_COMMANDS is defined
SLASH_COMPLETER = SlashCommandCompleter(SLASH_COMMANDS)


def get_theme():
    """Get current theme colors."""
    theme_name = config_mgr.get("theme", "default")
    return THEMES.get(theme_name, THEMES["default"])


def print_banner():
    theme = get_theme()
    thm = config_mgr.get('theme', 'default').title()

    ascii_art = [
        "$$$$$$$$\\                                                   $$$$$$\\                  $$\\",
        "$$  ____$$\\                                                  $$  __$$\\                 $$ |",
        "$$ |  $$ | $$$$$$\\   $$$$$$\\   $$$$$$\\   $$$$$$\\  $$$$$$$\\  $$ /  \\__| $$$$$$\\   $$$$$$$ | $$$$$$\\",
        "$$ |  $$ |$$  __$$\\ $$  __$$\\ $$  __$$\\  \\____$$\\ $$  __$$\\ $$ |      $$  __$$\\ $$  __$$ |$$  __$$\\",
        "$$ |  $$ |$$$$$$$$ |$$$$$$$$ |$$ /  $$ | $$$$$$$ |$$ |  $$ |$$ |      $$ /  $$ |$$ /  $$ |$$$$$$$$ |",
        "$$ |  $$ |$$   ____|$$   ____|$$ |  $$ |$$  __$$ |$$ |  $$ |$$ |  $$\\ $$ |  $$ |$$ |  $$ |$$   ____|",
        "$$$$$$$$  |\\$$$$$$\\$ \\$$$$$$\\$ $$$$$$$  |\\$$$$$$$ |$$ |  $$ |\\$$$$$$  |\\$$$$$$  |\\$$$$$$$ |\\$$$$$$\\$",
        "\\_______/  \\_______| \\_______|$$  ____/  \\_______|\\__|  \\__| \\______/  \\______/  \\_______| \\_______|",
        "                              $$ |",
        "                              $$ |",
        "                              \\__|",
    ]

    try:
        term_width = console.width
    except Exception:
        term_width = 80

    max_art_width = max(len(line) for line in ascii_art)
    art_padding = max(0, (term_width - max_art_width) // 2)
    primary_color = theme['primary']
    accent_color = theme['accent']

    out = console.file
    out.write("\n")
    for line in ascii_art:
        colored_line = ""
        i = 0
        while i < len(line):
            if line[i] == '$' and i + 1 < len(line) and line[i + 1] == '$':
                colored_line += f"\033[{get_color_code(primary_color)}m$$\033[0m"
                i += 2
            elif line[i] == '$':
                colored_line += f"\033[{get_color_code(primary_color)}m$\033[0m"
                i += 1
            elif line[i] in ['\\', '|', '/']:
                colored_line += f"\033[{get_color_code(accent_color)}m{line[i]}\033[0m"
                i += 1
            else:
                colored_line += line[i]
                i += 1
        out.write(" " * art_padding + colored_line + "\n")

    subtitle = f"Terminal AI Agent | DeepanCode AI Agent | {thm}"
    sub_padding = max(0, (term_width - len(subtitle)) // 2)
    out.write("\n" + " " * sub_padding + f"\033[{get_color_code(primary_color)}m{subtitle}\033[0m\n")

    help_text = "Type /help for commands or start typing your task"
    help_padding = max(0, (term_width - len(help_text)) // 2)
    out.write("\n" + " " * help_padding + f"\033[{get_color_code(accent_color)}m{help_text}\033[0m\n\n")
    out.flush()


def get_color_code(color_name):
    """Get ANSI escape code for Rich color name."""
    color_map = {
        "black": "30", "red": "31", "green": "32", "yellow": "33",
        "blue": "34", "magenta": "35", "cyan": "36", "white": "37",
        "bright_black": "90", "bright_red": "91", "bright_green": "92", "bright_yellow": "93",
        "bright_blue": "94", "bright_magenta": "95", "bright_cyan": "96", "bright_white": "97",
        "bright_orange": "91",
    }
    return color_map.get(color_name, "36")




def handle_slash_command(cmd_line):
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


def _announce_model_switch(model_id, provider, display_name=None, context_window=None):
    """Single shared 'MODEL SWITCHED SUCCESSFULLY' announcement + key check."""
    console.print()
    console.print("[bold green]MODEL SWITCHED SUCCESSFULLY[/bold green]")
    console.print(f"[green]Active Model:[/green] [bold]{display_name or model_id}[/bold]")
    console.print(f"[dim]  API ID: {model_id}[/dim]")
    console.print(f"[dim]  Provider: {provider.upper()}[/dim]")
    if context_window:
        console.print(f"[dim]  Context: {context_window // 1000}K tokens[/dim]")
    console.print()
    if not config_mgr.get_api_key(provider):
        console.print(f"[bold red]WARNING: No API key for {provider.upper()}![/bold red]")
        console.print(f"[dim]  Run: /connect {provider} <YOUR_API_KEY>[/dim]")
        console.print("[dim]  Without a key, this model will NOT work.[/dim]")
    else:
        console.print(f"[bold yellow]>>> Next request will use: {model_id} <<<[/bold yellow]")
    console.print()


def _cmd_model(parts, ctx):
    theme = ctx["theme"]
    if len(parts) > 1:
        arg = parts[1]
        models = get_all_models()
        if arg.isdigit() and 1 <= int(arg) <= len(models):
            selected = models[int(arg) - 1]
            config_mgr.set("model", selected["id"])
            config_mgr.set("provider", selected["provider"])
            _announce_model_switch(
                selected["id"], selected["provider"],
                selected.get("name"), selected.get("context_window"),
            )
        else:
            from deepans_code.models import get_all_models as _all
            info = get_model_info(arg)
            # get_model_info fabricates Custom entries for typos — reject them.
            known = {m["id"].lower() for m in _all()}
            if info.get("id", "").lower() not in known or info.get("name", "").lower().startswith("custom"):
                console.print(f"[red]Unknown model: {arg}[/red]")
                console.print("[dim]Use /model to list valid models.[/dim]")
                return True
            config_mgr.set("model", info["id"])
            config_mgr.set("provider", info["provider"])
            _announce_model_switch(info["id"], info["provider"], info.get("name"))
    else:
        current_model = config_mgr.get("model", "")
        console.print()
        console.print(f"[bold {theme['primary']}]All Available Models[/bold {theme['primary']}]")
        console.print(f"[dim]  Current active: {current_model}[/dim]")
        console.print()

        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1), expand=True)
        table.add_column("#", style="dim", justify="right", width=3, no_wrap=True)
        table.add_column("", style="bold green", width=2, no_wrap=True)
        table.add_column("Provider", style=theme['primary'], width=12, no_wrap=True)
        table.add_column("Model", style=f"bold {theme['accent']}", width=38, no_wrap=True)
        table.add_column("Context", style="dim", width=8, no_wrap=True)

        for idx, m in enumerate(get_all_models(), 1):
            is_active = m["id"].lower() == current_model.lower()
            model_style = "bold yellow" if is_active else f"bold {theme['accent']}"
            marker = ">>" if is_active else "  "
            table.add_row(
                str(idx),
                marker,
                m["provider"].upper(),
                Text(m["id"], style=model_style),
                f"{m['context_window']//1000}K"
            )

        console.print(table)
        console.print("[dim]  >> = active model[/dim]")
        console.print()

        try:
            choice = input(f"  Select (1-{len(get_all_models())}): ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(get_all_models()):
                selected = get_all_models()[int(choice) - 1]
                config_mgr.set("model", selected["id"])
                config_mgr.set("provider", selected["provider"])
                _announce_model_switch(
                    selected["id"], selected["provider"],
                    selected.get("name"), selected.get("context_window"),
                )
            elif choice:
                console.print("[dim]Invalid choice. Model not changed.[/dim]")
        except (KeyboardInterrupt, EOFError):
            console.print()
        console.print()
    return True


def _cmd_connect(parts, ctx):
    theme = ctx["theme"]
    if len(parts) >= 3:
        provider = parts[1].lower()
        key = " ".join(parts[2:])
        if provider not in PROVIDERS:
            console.print(f"[red]Unknown provider: {provider}[/red]")
            valid_list = ", ".join(list(PROVIDERS.keys())[:10]) + "..."
            console.print(f"[dim]Valid providers: {valid_list}[/dim]")
            return True
        try:
            config_mgr.set_connector(provider, key)
        except ValueError as e:
            console.print(f"[red]Invalid key: {e}[/red]")
            return True
        console.print()
        console.print(f"[green]API key saved for {PROVIDERS[provider]['name']}[/green]")
        console.print(f"[dim]  Provider: {provider.upper()}[/dim]")
        console.print(f"[dim]  Key saved ({len(key.strip())} chars, hidden for security)[/dim]")
        console.print()
    elif len(parts) == 2:
        provider = parts[1].lower()
        key = config_mgr.get_api_key(provider)
        console.print()
        if key:
            console.print(f"[cyan]{provider.upper()}[/cyan]: [green]Connected[/green] ({len(key)} chars)")
        else:
            console.print(f"[cyan]{provider.upper()}[/cyan]: [red]Not configured[/red]")
            console.print(f"[dim]  Add key: /connect {provider} <YOUR_KEY>[/dim]")
        console.print()
    else:
        # Build provider lists sorted A-Z
        free_providers = []
        paid_providers = []
        for prov_key, prov_data in sorted(PROVIDERS.items(), key=lambda x: x[1]["name"].lower()):
            model_count = len(prov_data.get("models", []))
            entry = (prov_key, prov_data, model_count)
            if prov_data.get("free_tier"):
                free_providers.append(entry)
            else:
                paid_providers.append(entry)

        console.print()
        console.print(f"[bold {theme['primary']}]=== ALL LLM PROVIDERS ({len(PROVIDERS)} total) ===[/bold {theme['primary']}]")
        console.print()

        # === FREE PROVIDERS (A-Z) ===
        console.print(f"[bold green]--- FREE PROVIDERS ({len(free_providers)}) ---[/bold green]")
        console.print()
        idx = 1
        provider_map = {}
        for prov_key, prov_data, model_count in free_providers:
            key_env = prov_data.get("key_env")
            keyless = "[green]KEYLESS[/green]" if key_env is None else "[dim]needs key[/dim]"
            status = config_mgr.get_api_key(prov_key)
            status_tag = "[green]ON[/green]" if status else "[dim]OFF[/dim]"
            console.print(f"  [bold cyan]{idx:2}.[/bold cyan] {prov_data['name']:25} {model_count:3} models  {keyless:20} {status_tag}")
            provider_map[str(idx)] = prov_key
            idx += 1

        console.print()

        # === PAID PROVIDERS (A-Z) ===
        console.print(f"[bold yellow]--- PAID PROVIDERS ({len(paid_providers)}) ---[/bold yellow]")
        console.print()
        for prov_key, prov_data, model_count in paid_providers:
            key_env = prov_data.get("key_env")
            keyless = "[green]KEYLESS[/green]" if key_env is None else "[dim]needs key[/dim]"
            status = config_mgr.get_api_key(prov_key)
            status_tag = "[green]ON[/green]" if status else "[dim]OFF[/dim]"
            console.print(f"  [bold cyan]{idx:2}.[/bold cyan] {prov_data['name']:25} {model_count:3} models  {keyless:20} {status_tag}")
            provider_map[str(idx)] = prov_key
            idx += 1

        console.print()
        console.print(f"[dim]  Total: {len(PROVIDERS)} providers, {sum(len(p.get('models', [])) for p in PROVIDERS.values())} models[/dim]")
        console.print()
        console.print(f"  [bold green]KEYLESS[/bold green] = No API key needed (start immediately)")
        console.print(f"  [dim]needs key[/dim] = Get free key from provider website")
        console.print()
        console.print(f"  [dim]Usage: /connect <provider> <API_KEY>[/dim]")
        console.print(f"  [dim]Example: /connect groq gsk_xxxxxxxxxxxxxxxx[/dim]")
        console.print()

        try:
            choice = input(f"  Select provider (1-{idx-1}) or press Enter to skip: ").strip()
            if choice and choice in provider_map:
                selected_key = provider_map[choice]
                prov_data = PROVIDERS[selected_key]
                console.print()
                console.print(f"[cyan]Selected: {prov_data['name']}[/cyan]")
                console.print(f"[dim]  {prov_data.get('description', '')}[/dim]")
                console.print(f"[dim]  URL: {prov_data.get('url', '')}[/dim]")
                console.print()
                if prov_data.get("key_env") is None:
                    console.print("[green]This provider is KEYLESS - no API key needed![/green]")
                    console.print(f"[dim]  Models: {', '.join([m['id'] for m in prov_data.get('models', [])[:5]])}[/dim]")
                else:
                    try:
                        import getpass as _gp
                        key = _gp.getpass("  Enter API key (hidden): ").strip()
                    except Exception:
                        key = input("  Enter API key: ").strip()
                    if key:
                        try:
                            config_mgr.set_connector(selected_key, key)
                            console.print(f"[green]API key saved![/green]")
                        except ValueError as e:
                            console.print(f"[red]Invalid key: {e}[/red]")
                    else:
                        console.print("[dim]No key entered.[/dim]")
            elif choice:
                console.print("[dim]Invalid choice.[/dim]")
        except (KeyboardInterrupt, EOFError):
            console.print()
        console.print()
    return True


def _cmd_effort(parts, ctx):
    theme = ctx["theme"]
    if len(parts) > 1 and parts[1].lower() in ["low", "medium", "high"]:
        config_mgr.set("effort", parts[1].lower())
        console.print(f"[green]Effort set to:[/green] [bold magenta]{parts[1].upper()}[/bold magenta]")
    else:
        current = config_mgr.get("effort", "medium")
        console.print()
        console.print(f"[bold {theme['primary']}]Select Effort Level[/bold {theme['primary']}]")
        console.print()
        console.print(f"  [bold cyan]1.[/bold cyan] Low    - Fast, minimal reasoning")
        console.print(f"  [bold cyan]2.[/bold cyan] Medium - Balanced analysis")
        console.print(f"  [bold cyan]3.[/bold cyan] High   - Deep step-by-step reasoning")
        console.print()
        console.print(f"  [dim]Current: {current.upper()}[/dim]")
        console.print()

        try:
            choice = input("  Select (1, 2 or 3): ").strip()
            effort_map = {"1": "low", "2": "medium", "3": "high"}
            if choice in effort_map:
                config_mgr.set("effort", effort_map[choice])
                console.print(f"[green]Effort set to:[/green] [bold magenta]{effort_map[choice].upper()}[/bold magenta]")
            else:
                console.print("[dim]Invalid choice.[/dim]")
        except (KeyboardInterrupt, EOFError):
            console.print()
        console.print()
    return True


def _cmd_mode(parts, ctx):
    theme = ctx["theme"]
    valid_modes = ["code", "architect", "ask", "debug", "review"]
    mode_desc = {
        "code": "Implement features, refactor, fix bugs",
        "architect": "System design, architecture, specs",
        "ask": "Answer questions, explain code",
        "debug": "Investigate errors, diagnose issues",
        "review": "Audit code, security, performance"
    }
    if len(parts) > 1 and parts[1].lower() in valid_modes:
        config_mgr.set("mode", parts[1].lower())
        console.print(f"[green]Mode set to:[/green] [bold blue]{parts[1].upper()}[/bold blue]")
    else:
        current = config_mgr.get("mode", "code")
        console.print()
        console.print(f"[bold {theme['primary']}]Select Mode[/bold {theme['primary']}]")
        console.print()
        for i, mode in enumerate(valid_modes, 1):
            marker = " <-" if mode == current else ""
            console.print(f"  [bold cyan]{i}.[/bold cyan] {mode.title():12} - {mode_desc[mode]}{marker}")
        console.print()
        console.print(f"  [dim]Current: {current.upper()}[/dim]")
        console.print()

        try:
            choice = input("  Select (1-5): ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(valid_modes):
                selected = valid_modes[int(choice) - 1]
                config_mgr.set("mode", selected)
                console.print(f"[green]Mode set to:[/green] [bold blue]{selected.upper()}[/bold blue]")
            else:
                console.print("[dim]Invalid choice.[/dim]")
        except (KeyboardInterrupt, EOFError):
            console.print()
        console.print()
    return True


def _cmd_themes(parts, ctx):
    theme = ctx["theme"]
    if len(parts) > 1 and parts[1].lower() in THEMES:
        config_mgr.set("theme", parts[1].lower())
        console.print(f"[green]Theme set to:[/green] [bold]{THEMES[parts[1].lower()]['name']}[/bold]")
        print_banner()
    else:
        current = config_mgr.get("theme", "default")
        theme_list = list(THEMES.keys())
        console.print()
        console.print(f"[bold {theme['primary']}]Select Theme[/bold {theme['primary']}]")
        console.print()
        for i, (key, t) in enumerate(THEMES.items(), 1):
            marker = " <-" if key == current else ""
            console.print(f"  [bold {t['font']}]{i:2}.[/bold {t['font']}] {t['name']:20} [bold {t['font']}]██████[/bold {t['font']}]{marker}")
        console.print()
        console.print(f"  [dim]Current: {THEMES[current]['name']}[/dim]")
        console.print()

        try:
            choice = input(f"  Select (1-{len(theme_list)}): ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(theme_list):
                selected = theme_list[int(choice) - 1]
                config_mgr.set("theme", selected)
                console.print(f"[green]Theme set to:[/green] [bold]{THEMES[selected]['name']}[/bold]")
                print_banner()
            else:
                console.print("[dim]Invalid choice.[/dim]")
        except (KeyboardInterrupt, EOFError):
            console.print()
        console.print()
    return True


def _cmd_agents(parts, ctx):
    theme = ctx["theme"]
    if len(parts) > 1 and parts[1].lower() in ["plan", "build"]:
        config_mgr.set("agent", parts[1].lower())
        agent_type = parts[1].lower()
        if agent_type == "plan":
            console.print(f"[green]Agent set to:[/green] [bold yellow]Plan[/bold yellow]")
            console.print("[dim]Plan agent focuses on: Design, Architecture, Strategy, Analysis[/dim]")
        else:
            console.print(f"[green]Agent set to:[/green] [bold yellow]Build[/bold yellow]")
            console.print("[dim]Build agent focuses on: Implementation, Coding, Testing, Deployment[/dim]")
    else:
        current = config_mgr.get("agent", "build")
        console.print()
        console.print(f"[bold {theme['primary']}]Select Agent Type[/bold {theme['primary']}]")
        console.print()
        console.print(f"  [bold cyan]1.[/bold cyan] [bold yellow]Plan[/bold yellow]   - Design, Architecture, Strategy, Analysis")
        console.print(f"  [bold cyan]2.[/bold cyan] [bold yellow]Build[/bold yellow]  - Implementation, Coding, Testing, Deployment")
        console.print()
        console.print(f"  [dim]Current: {current.title()}[/dim]")
        console.print()
        console.print("  [dim]Plan agent = Think before you code[/dim]")
        console.print("  [dim]Build agent = Code it now[/dim]")
        console.print()

        try:
            choice = input("  Select (1 or 2): ").strip()
            if choice == "1":
                config_mgr.set("agent", "plan")
                console.print(f"[green]Agent set to:[/green] [bold yellow]Plan[/bold yellow]")
                console.print("[dim]Plan agent focuses on: Design, Architecture, Strategy, Analysis[/dim]")
            elif choice == "2":
                config_mgr.set("agent", "build")
                console.print(f"[green]Agent set to:[/green] [bold yellow]Build[/bold yellow]")
                console.print("[dim]Build agent focuses on: Implementation, Coding, Testing, Deployment[/dim]")
            else:
                console.print("[dim]Invalid choice.[/dim]")
        except (KeyboardInterrupt, EOFError):
            console.print()
        console.print()
    return True


def _cmd_mcp(parts, ctx):
    theme = ctx["theme"]
    if len(parts) == 1 or parts[1].lower() == "list":
        console.print(Panel(mcp_mgr.list_servers(), title="MCP Servers", border_style="cyan"))
    elif parts[1].lower() == "add" and len(parts) >= 4:
        name = parts[2]
        command = parts[3]
        args = parts[4:]
        res = mcp_mgr.add_stdio_server(name, command, args)
        console.print(f"[green]{res}[/green]")
    elif parts[1].lower() == "remove" and len(parts) >= 3:
        res = mcp_mgr.remove_server(parts[2])
        console.print(f"[yellow]{res}[/yellow]")
    elif parts[1].lower() == "toggle" and len(parts) >= 3:
        res = mcp_mgr.toggle_server(parts[2])
        console.print(f"[cyan]{res}[/cyan]")
    else:
        console.print("[dim]Usage: /mcp list | /mcp add <name> <cmd> [args] | /mcp remove <name> | /mcp toggle <name>[/dim]")
    return True


def _cmd_skills(parts, ctx):
    theme = ctx["theme"]
    from deepans_code.skill_manager import skill_mgr
    if len(parts) == 1 or parts[1].lower() == "list":
        skill_list = skill_mgr.list_skills()
        if skill_list:
            table = Table(show_header=True, header_style=f"bold {theme['primary']}", box=None, padding=(0, 2))
            table.add_column("Name", style=theme['primary'], no_wrap=True)
            table.add_column("Description", style="white")
            table.add_column("Status", style="green")
            for s in skill_list:
                status = "[green]ENABLED[/green]" if s["enabled"] else "[dim]disabled[/dim]"
                table.add_row(s["name"], s["description"], status)
            console.print(Panel(table, title="[bold]Available Skills[/bold]", border_style=theme['border']))
        else:
            console.print("[dim]No skills found. Use /skills import <file.md> to add one.[/dim]")
    elif parts[1].lower() == "import" and len(parts) >= 3:
        file_path = parts[2]
        result = skill_mgr.import_skill(file_path)
        if result["success"]:
            console.print(f"[green]Skill imported successfully![/green]")
            console.print(f"[dim]  Name: {result['name']}[/dim]")
            console.print(f"[dim]  Path: {result['path']}[/dim]")
            console.print(f"[dim]  Use /skills enable {result['name']} to activate it[/dim]")
        else:
            console.print(f"[red]Import failed:[/red] {result['error']}")
    elif parts[1].lower() == "enable" and len(parts) >= 3:
        skill_name = parts[2]
        result = skill_mgr.enable_skill(skill_name)
        if result["success"]:
            console.print(f"[green]{result['message']}[/green]")
            console.print(f"[dim]Skill will be active in next conversation turn.[/dim]")
        else:
            console.print(f"[red]Enable failed:[/red] {result['error']}")
    elif parts[1].lower() == "disable" and len(parts) >= 3:
        skill_name = parts[2]
        result = skill_mgr.disable_skill(skill_name)
        if result["success"]:
            console.print(f"[yellow]{result['message']}[/yellow]")
            console.print(f"[dim]Skill will be removed from context in next conversation turn.[/dim]")
        else:
            console.print(f"[red]Disable failed:[/red] {result['error']}")
    elif parts[1].lower() == "remove" and len(parts) >= 3:
        skill_name = parts[2]
        result = skill_mgr.remove_skill(skill_name)
        if result["success"]:
            console.print(f"[yellow]Skill '{skill_name}' removed.[/yellow]")
        else:
            console.print(f"[red]Remove failed:[/red] {result['error']}")
    elif parts[1].lower() == "show" and len(parts) >= 3:
        skill_name = parts[2]
        content = skill_mgr.get_skill_content(skill_name)
        if content:
            console.print(Panel(content, title=f"[bold]{skill_name}[/bold]", border_style=theme['border']))
        else:
            console.print(f"[red]Skill '{skill_name}' not found.[/red]")
    else:
        console.print("[dim]Usage: /skills [list] | /skills import <file.md> | /skills enable <name> | /skills disable <name> | /skills remove <name> | /skills show <name>[/dim]")
    return True


def _cmd_metrics(parts, ctx):
    theme = ctx["theme"]
    try:
        from deepans_code.metrics import metrics
        dashboard = metrics.format_dashboard()
        console.print(Panel(dashboard, title="[bold]Performance Dashboard[/bold]", border_style="cyan"))
    except Exception as e:
        console.print(f"[red]Metrics unavailable: {e}[/red]")
    return True


def _cmd_history(parts, ctx):
    theme = ctx["theme"]
    try:
        from deepans_code.database import db
        convs = db.get_conversations(limit=10)
        if not convs:
            console.print("[dim]No conversation history found.[/dim]")
        else:
            table = Table(show_header=True, header_style=f"bold {theme['primary']}", box=None, padding=(0, 2))
            table.add_column("#", style="dim", justify="right", width=4)
            table.add_column("Title", style=theme['primary'])
            table.add_column("Model", style="dim")
            table.add_column("Messages", justify="right")
            table.add_column("Date", style="dim")
            for i, conv in enumerate(convs, 1):
                import datetime
                dt = datetime.datetime.fromtimestamp(conv.get("updated_at", 0))
                date_str = dt.strftime("%Y-%m-%d %H:%M")
                table.add_row(
                    str(i),
                    conv.get("title", "Untitled"),
                    conv.get("model", "N/A")[:30],
                    str(conv.get("message_count", 0)),
                    date_str
                )
            console.print(Panel(table, title="[bold]Conversation History[/bold]", border_style=theme['border']))
    except Exception as e:
        console.print(f"[red]History unavailable: {e}[/red]")
    return True


def _cmd_export(parts, ctx):
    theme = ctx["theme"]
    try:
        from deepans_code.database import db
        raw_fmt = (parts[1] if len(parts) > 1 else "markdown").lower()
        fmt_map = {"md": "markdown", "markdown": "markdown", "json": "json"}
        if raw_fmt not in fmt_map:
            console.print("[red]Usage: /export [md|json][/red]")
            return True
        fmt = fmt_map[raw_fmt]
        ext = "md" if fmt == "markdown" else "json"
        if get_agent().conversation_id:
            content = db.export_conversation(get_agent().conversation_id, fmt=fmt)
            export_path = Path.home() / ".deepans-code" / f"export_{int(time.time())}.{ext}"
            export_path.write_text(content, encoding="utf-8")
            console.print(f"[green]Exported to: {export_path}[/green]")
        else:
            console.print("[dim]No active conversation to export.[/dim]")
    except Exception as e:
        console.print(f"[red]Export failed: {e}[/red]")
    return True


def _cmd_cache(parts, ctx):
    theme = ctx["theme"]
    try:
        from deepans_code.cache import response_cache
        subcmd = parts[1] if len(parts) > 1 else "stats"
        if subcmd == "clear":
            response_cache.clear()
            console.print("[green]Cache cleared.[/green]")
        else:
            stats = response_cache.stats()
            console.print(Panel(
                f"Memory: {stats['memory']['size']}/{stats['memory']['max_size']} entries\n"
                f"Hit Rate: {stats['memory']['hit_rate']*100:.1f}%\n"
                f"Disk: {stats['disk']['entries']} entries, {stats['disk']['size_mb']:.1f} MB",
                title="[bold]Cache Stats[/bold]",
                border_style="cyan"
            ))
    except Exception as e:
        console.print(f"[red]Cache unavailable: {e}[/red]")
    return True


def _cmd_plugins(parts, ctx):
    theme = ctx["theme"]
    try:
        from deepans_code.plugin_manager import plugin_manager
        plugins = plugin_manager.get_all_plugins()
        if not plugins:
            console.print("[dim]No plugins loaded.[/dim]")
        else:
            table = Table(show_header=True, header_style=f"bold {theme['primary']}", box=None, padding=(0, 2))
            table.add_column("Name", style=theme['primary'])
            table.add_column("Version", style="dim")
            table.add_column("Description")
            for p in plugins:
                table.add_row(p.name, p.version, p.description)
            console.print(Panel(table, title="[bold]Loaded Plugins[/bold]", border_style=theme['border']))
    except Exception as e:
        console.print(f"[red]Plugins unavailable: {e}[/red]")
    return True


def _cmd_switch(parts, ctx):
    theme = ctx["theme"]
    # Quick provider/model switch for handling errors
    fallback_providers = {
        "opencode": "openrouter",
        "openrouter": "opencode"
    }
    current_provider = config_mgr.get("provider", "openrouter")
    fallback = fallback_providers.get(current_provider, "openrouter")

    if len(parts) > 1:
        target = parts[1].lower()
        if target in ["opencode", "openrouter"]:
            config_mgr.set("provider", target)
            console.print(f"[green]Switched to provider:[/green] [bold]{target.upper()}[/bold]")
            # Suggest a model for the new provider
            if target == "openrouter":
                console.print("[dim]Suggested model: /model meta-llama/llama-3.3-70b-instruct:free[/dim]")
            else:
                console.print("[dim]Suggested model: /model mimo-v2.5-free[/dim]")
        else:
            console.print("[dim]Usage: /switch openrouter | /switch opencode[/dim]")
    else:
        # Auto-switch to fallback
        config_mgr.set("provider", fallback)
        console.print(f"[green]Auto-switched to:[/green] [bold]{fallback.upper()}[/bold]")
        console.print(f"[dim]Previous provider '{current_provider}' was experiencing issues.[/dim]")
        if fallback == "openrouter":
            console.print("[dim]Recommended model: meta-llama/llama-3.3-70b-instruct:free[/dim]")
        else:
            console.print("[dim]Recommended model: mimo-v2.5-free[/dim]")
    console.print()
    return True


# Register every handler into the single cli_commands registry.
from deepans_code.cli_commands import register as _register_command
_register_command("/model", _cmd_model)
_register_command("/connectors", _cmd_connect)
_register_command("/connector", _cmd_connect)
_register_command("/connect", _cmd_connect)
_register_command("/effort", _cmd_effort)
_register_command("/mode", _cmd_mode)
_register_command("/themes", _cmd_themes)
_register_command("/agents", _cmd_agents)
_register_command("/mcp", _cmd_mcp)
_register_command("/skills", _cmd_skills)
_register_command("/metrics", _cmd_metrics)
_register_command("/history", _cmd_history)
_register_command("/export", _cmd_export)
_register_command("/cache", _cmd_cache)
_register_command("/plugins", _cmd_plugins)
_register_command("/switch", _cmd_switch)

COMMAND_HANDLERS = __import__("deepans_code.cli_commands", fromlist=["COMMAND_HANDLERS"]).COMMAND_HANDLERS

# Rebuild the canonical list now that every handler is registered.
SLASH_COMMANDS = _slash_commands()
SLASH_COMPLETER = SlashCommandCompleter(SLASH_COMMANDS)


def _run_search_flow(user_input, theme):
    """Inline /search flow: list matches, apply selection. Always returns True."""
    query = user_input[len("/search "):].strip()
    results = search_models_providers(query)
    if results:
        console.print()
        console.print(f"[bold {theme['primary']}]Search Results for: '{query}'[/bold {theme['primary']}]")
        console.print()
        for i, r in enumerate(results, 1):
            console.print(f"  [bold cyan]{i}.[/bold cyan] {r}")
        console.print()
        try:
            choice = input(f"  Select (1-{len(results)}) or press Enter: ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(results):
                selected = results[int(choice) - 1]
                # Handle the selected result
                if selected.startswith("model:"):
                    model_id = selected.split(":", 1)[1]
                    config_mgr.set("model", model_id)
                    console.print(f"[green]Model set to: {model_id}[/green]")
                elif selected.startswith("provider:"):
                    prov_id = selected.split(":", 1)[1]
                    config_mgr.set("provider", prov_id)
                    console.print(f"[green]Provider set to: {prov_id}[/green]")
                elif selected.startswith("command:"):
                    cmd = selected.split(":", 1)[1]
                    console.print(f"[cyan]Command: {cmd}[/cyan]")
                else:
                    console.print(f"[dim]{selected}[/dim]")
            elif choice:
                console.print("[dim]Invalid choice.[/dim]")
        except (KeyboardInterrupt, EOFError):
            console.print()
    else:
        console.print(f"[dim]No results found for: '{query}'[/dim]")
    console.print()
    return True


def _make_think_panel(text, done=False):
    lines = text.splitlines()
    line_count = len(lines)
    label = "\U0001F9E0 Thinking" + (" done" if done else " ...")
    count_label = f"{line_count} line{'s' if line_count != 1 else ''}"
    display = text if line_count <= 40 else (
        "\n".join(lines[:40]) + f"\n\n... ({line_count - 40} more lines)"
    )
    return Panel(
        Text(display, style="dim italic"),
        title=f"[bold dim cyan]{label}[/bold dim cyan]  [dim]({count_label})[/dim]",
        border_style="dim cyan",
        padding=(0, 1),
    )


def _run_agent_turn(user_input):
    """Stream one agent turn to the terminal (thinking/tools/assistant/error)."""
    console.print()
    thinking_enabled = config_mgr.get("thinking", True)
    think_text_so_far = ""
    thinking_panel_shown = False

    with Live(
        Spinner("dots", text="[cyan]Thinking...[/cyan]"),
        refresh_per_second=15,
        console=console,
        transient=True,
    ) as live:
        for event_type, event_data in get_agent().send_message_stream(user_input):

            if event_type == "thinking_chunk":
                if thinking_enabled:
                    think_text_so_far += event_data
                    thinking_panel_shown = True
                    live.update(_make_think_panel(think_text_so_far, done=False))

            elif event_type == "thinking_done":
                if thinking_enabled:
                    if event_data:
                        think_text_so_far = event_data
                    thinking_panel_shown = True
                    live.update(_make_think_panel(think_text_so_far, done=True))

            elif event_type == "tool_call":
                live.stop()
                if thinking_panel_shown:
                    console.print(_make_think_panel(think_text_so_far, done=True))
                    thinking_panel_shown = False
                console.print(f"[bold yellow]>>[/bold yellow] [yellow]{event_data}[/yellow]")
                live.start()
                live.update(Spinner("dots", text="[yellow]Running...[/yellow]"))

            elif event_type == "tool_result":
                live.stop()
                lines = event_data.splitlines()
                preview = "\n".join(lines[:15]) + ("\n..." if len(lines) > 15 else "")
                console.print(Panel(preview, title="[dim green]Output[/dim green]", border_style="dim green"))
                live.start()
                live.update(Spinner("dots", text="[cyan]Continuing...[/cyan]"))

            elif event_type == "assistant":
                live.stop()
                console.print()
                console.print(Markdown(event_data))
                console.print()

            elif event_type == "error":
                live.stop()
                console.print(f"\n[bold red]Error:[/bold red] {event_data}\n")
                # Recover gracefully from auth failures by prompting for a key
                if "Authentication failed" in event_data or "401" in event_data:
                    try:
                        console.print(
                            "[yellow]Paste a valid API key to continue "
                            "(or press Enter to skip):[/yellow]"
                        )
                        new_key = input("> ").strip()
                        if new_key:
                            prov = config_mgr.get("provider", "openrouter")
                            config_mgr.set_connector(prov, new_key)
                            console.print(
                                f"[green]API key saved for {prov}. "
                                f"Please re-run your prompt.[/green]"
                            )
                    except (KeyboardInterrupt, EOFError):
                        pass

    console.print()

def run_cli(argv=None):
    """Entry point: `deepans-code [--help|--version]` else interactive REPL."""
    import sys as _sys

    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("-h", "--help", "help"):
        console.print(f"[bold cyan]{__app_name__} {__version__}[/bold cyan] — terminal AI coding agent")
        console.print()
        console.print("Usage: deepans-code [--help | --version]")
        console.print("Interactive commands: /help /model /connect /status /clear /exit")
        return 0
    if args and args[0] in ("-V", "--version", "version"):
        console.print(f"{__app_name__} {__version__}")
        return 0
    if args:
        console.print(f"[red]Unknown argument: {args[0]}[/red] (try --help)")
        return 2
    print_banner()

    session = None
    if PROMPT_TOOLKIT_AVAILABLE:
        try:
            session = PromptSession(
                history=InMemoryHistory(),
                completer=SLASH_COMPLETER,
                key_bindings=KB,
                complete_while_typing=True,
                complete_in_thread=True,
            )
        except Exception:
            session = None

    while True:
        try:
            theme = get_theme()

            current_model = config_mgr.get("model", "")

            usage_stats = get_agent().get_token_usage()
            tokens_used = usage_stats["total_used"]
            percentage = usage_stats["percentage"]
            prompt_tokens = usage_stats["total_prompt"]
            completion_tokens = usage_stats["total_completion"]
            context_window = usage_stats["context_window"]
            response_time = usage_stats["response_time"]

            if tokens_used >= 1000:
                token_display = f"{tokens_used/1000:.1f}K"
            else:
                token_display = str(tokens_used)

            print_status_bar_right(token_display, percentage, prompt_tokens, completion_tokens, context_window, response_time,
                          location_path=str(Path.home() / ".deepans-code"), version=__version__, mode=config_mgr.get("mode", "code"), mcp_status=mcp_mgr.list_servers()[:1] if mcp_mgr.list_servers() else "")

            if PROMPT_TOOLKIT_AVAILABLE and session:
                # Show search prompt if user typed /search or // 
                user_input = session.prompt(HTML(f'<ansibrightgreen><b>></b></ansibrightgreen> ')).strip()
            else:
                console.print(f"[bold {theme['primary']}]>[/bold {theme['primary']}] ", end="")
                user_input = input().strip()

            if not user_input:
                continue

            # Handle search bar - type /search to search models/providers
            if user_input.startswith("/search "):
                _run_search_flow(user_input, theme)
                continue

            if handle_slash_command(user_input):
                continue

            # API Key checks
            if not config_mgr.get_api_key("openrouter") and not config_mgr.get_api_key("opencode"):
                console.print("[yellow]No API key found. Please enter your OpenRouter or OpenCode Zen API key to continue:[/yellow]")
                user_input = input("> ").strip()
                if not user_input:
                    continue
                if user_input.startswith("sk-or-"):
                    config_mgr.set_connector("openrouter", user_input)
                    console.print("[green]Automatically saved as OpenRouter API Key.[/green]")
                else:
                    config_mgr.set_connector("opencode", user_input)
                    console.print("[green]Automatically saved as OpenCode Zen API Key.[/green]")
                console.print("[dim]You can now use the models. Type your prompt again.[/dim]\n")
                continue

            _run_agent_turn(user_input)

        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Goodbye![/yellow]")
            break
        except Exception as e:
            console.print(f"[bold red]Error:[/bold red] {str(e)}")


def print_status_bar_right(token_display, percentage, prompt_tokens=0, completion_tokens=0, context_window=0, response_time=0.0,
                          location_path="", version="DeepanCode", mode="code", mcp_status=""):
    """Print interactive status bar with enhanced info."""
    theme = get_theme()
    agent_type = config_mgr.get("agent", "build").title()
    model = config_mgr.get("model", "")
    provider = config_mgr.get("provider", "openrouter").title()
    effort = config_mgr.get("effort", "medium").lower()

    if "/" in model:
        model_display = model.split("/")[-1]
    else:
        model_display = model

    model_display = model_display.replace("-", " ").title()
    if "Free" not in model_display:
        model_display = model_display + " Free"

    primary = theme['primary']

    # Build progress bar for context usage
    bar_width = 15
    filled = int(bar_width * min(percentage / 100, 1.0))
    bar = "█" * filled + "░" * (bar_width - filled)

    # MCP status on right side
    mcp_display = ""
    if mcp_status:
        mcp_display = f"[dim]│[/dim] [bold green]MCP: {mcp_status}[/bold green]"

    status_line = (
        f"[bold {primary}]{agent_type}[/bold {primary}] "
        f"[dim]│[/dim] "
        f"[bold]{model_display}[/bold] "
        f"[dim]{provider}[/dim] [dim]{version}[/dim] "
        f"[dim]│[/dim] "
        f"[bold {primary}]{effort}[/bold {primary}] "
        f"[bold blue]{mode}[/bold blue] "
        f"[dim]│[/dim] "
        f"[cyan]{bar}[/cyan] [dim]{percentage:.0f}%[/dim] "
        f"[dim]│[/dim] "
        f"[bold cyan]{response_time:.1f}s[/bold cyan] "
        f"{mcp_display}"
    )

    console.print(status_line)


if __name__ == "__main__":
    run_cli()


def search_models_providers(query, limit=50):
    """Search through available models and providers (complete results, capped)."""
    results = []
    query_lower = (query or "").lower()

    # Search through PROVIDERS (all matches; dedupe keeps it clean)
    for prov_key, prov_data in PROVIDERS.items():
        # Check model IDs
        for model in prov_data.get("models", []):
            if not isinstance(model, dict):
                continue
            mid = str(model.get("id", ""))
            mname = str(model.get("name", ""))
            if query_lower in mid.lower() or query_lower in mname.lower():
                results.append(f"model: {mid}")

        # Check provider name
        if query_lower in str(prov_data.get("name", "")).lower():
            results.append(f"provider: {prov_key}")

    # Search through SLASH_COMMANDS
    for cmd in SLASH_COMMANDS:
        if query_lower in cmd.lower():
            results.append(f"command: {cmd}")

    # Remove duplicates while preserving order, then cap for display.
    seen = set()
    unique_results = []
    for r in results:
        if r not in seen:
            seen.add(r)
            unique_results.append(r)
        if len(unique_results) >= limit:
            break

    return unique_results
