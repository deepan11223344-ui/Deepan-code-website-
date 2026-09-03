# DeepanCode v3.0.0

> Terminal AI Agent for Windows PowerShell & Linux Terminals

DeepanCode is a powerful, secure, and extensible CLI-based AI coding agent that reads, writes, edits, and executes code autonomously using free LLM models via OpenRouter and OpenCode Zen APIs.

## Features

- **Multi-turn Agent**: Autonomous code generation with tool calling and streaming
- **Security**: AES-256 encryption, command sandboxing, workspace boundary, input sanitization
- **Persistence**: SQLite database for conversation history across sessions
- **Parallel Execution**: Run multiple tools simultaneously for faster task completion
- **Caching**: LRU memory + disk cache for API responses and tool results
- **Metrics**: Real-time performance monitoring and health dashboards
- **Plugin System**: Extensible architecture with dependency injection
- **Rich UI**: Terminal UI with spinners, progress bars, and syntax highlighting
- **Web Integration**: DuckDuckGo web search + URL fetch with response caching

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/deepan/deepans-code.git
cd deepans-code

# Install in development mode
pip install -e ".[dev]"

# Or install with all features
pip install -e ".[full]"
```

### First Run

```bash
# Launch DeepanCode
deepans-code

# Or run as module
python -m deepans_code
```

### Setup API Key

```bash
# Set OpenRouter API key
/connect openrouter sk-or-your-key-here

# Or set OpenCode Zen API key
/connect opencode your-key-here
```

## Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all available commands |
| `/model` | List and switch LLM models |
| `/model <#>` | Switch to model by number |
| `/connect <provider> <key>` | Save API key |
| `/effort` | Set thinking depth (low/medium/high) |
| `/mode` | Switch mode (code/architect/ask/debug/review) |
| `/themes` | Change color theme |
| `/think <on\|off>` | Toggle thinking display |
| `/mcp` | Manage MCP servers |
| `/skills` | Manage agent skills |
| `/status` | Show session info and metrics |
| `/metrics` | Show performance dashboard |
| `/history` | Browse conversation history |
| `/export [md\|json]` | Export conversation |
| `/clear` | Clear conversation |
| `/switch` | Quick switch provider |
| `/exit` | Exit DeepanCode |

## Modes

- **Code**: Implement features, refactor, fix bugs
- **Architect**: System design, architecture, specs
- **Ask**: Answer questions, explain code
- **Debug**: Investigate errors, diagnose issues
- **Review**: Audit code, security, performance

## Agent Types

- **Plan**: Think before you code - design, architecture, strategy
- **Build**: Code it now - implementation, testing, deployment

## Architecture

```
deepans_code/
├── __init__.py          # Package metadata
├── __main__.py          # Entry point
├── agent.py             # Core agentic loop
├── cli.py               # Terminal UI (Rich + Prompt Toolkit)
├── client.py            # HTTP client for LLM APIs
├── config.py            # Configuration management
├── models.py            # LLM model definitions
├── tools.py             # Tool definitions and execution
├── system_prompt.py     # System prompt generator
├── token_usage.py       # Token tracking
├── security.py          # Security (sandbox, encryption, rate limiting)
├── database.py          # SQLite persistence
├── error_recovery.py    # Error handling and retry logic
├── model_health.py      # Model health checks
├── web_search.py        # Web search integration
├── rag.py               # RAG with vector store
├── cache.py             # LRU and disk caching
├── metrics.py           # Performance monitoring
├── plugin_manager.py    # Plugin architecture
├── async_executor.py    # Parallel tool execution
├── terminal_ui.py       # Rich terminal UI helpers
├── interactive_output.py # Live output
├── logging_config.py    # Structured logging
└── skills/              # Agent skills
```

## Configuration

Configuration is stored at `~/.deepans-code/config.json`:

```json
{
  "provider": "openrouter",
  "model": "openrouter/free",
  "effort": "medium",
  "mode": "code",
  "agent": "build",
  "thinking": true,
  "theme": "default"
}
```

## Environment Variables

```bash
# API Keys (alternative to /connect)
export OPENROUTER_API_KEY="sk-or-..."
export OPENCODE_API_KEY="..."

# Configuration
export DEEPANCODE_CONFIG_DIR="~/.deepans-code"
```

## Docker

```bash
# Build image
docker build -t deepans-code .

# Run container
docker run -it \
  -e OPENROUTER_API_KEY="sk-or-..." \
  -v ~/.deepans-code:/root/.deepans-code \
  deepans-code
```

## Development

### Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ -v --cov=deepans_code --cov-report=html

# Run specific test file
pytest tests/test_tools.py -v

# Run integration tests only
pytest tests/ -v -m integration
```

### Code Quality

```bash
# Lint
flake8 deepans_code/

# Format
black deepans_code/

# Sort imports
isort deepans_code/

# Type check
mypy deepans_code/
```

### Building

```bash
# Install build tools
pip install build

# Build package
python -m build

# Upload to PyPI
twine upload dist/*
```

## Plugin Development

Create a plugin and register it via `deepans_code/plugin_manager.py`
(skills live under `deepans_code/skills/`):

```python
from deepans_code.plugin_manager import Plugin

class MyPlugin(Plugin):
    @property
    def name(self) -> str:
        return "my-plugin"

    @property
    def version(self) -> str:
        return "1.0.0"

    def get_tools(self):
        return [{
            "type": "function",
            "function": {
                "name": "my_tool",
                "description": "My custom tool",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "input": {"type": "string"}
                    },
                    "required": ["input"]
                }
            }
        }]

    def execute_tool(self, name, args):
        if name == "my_tool":
            return f"Result: {args['input']}"
        return None

def register(manager):
    manager.register(MyPlugin())
```

## License

MIT License

## Author

Deepan
