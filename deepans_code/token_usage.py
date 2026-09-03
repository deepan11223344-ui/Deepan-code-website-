"""
OpenCode-Style Token Usage Tracking System for DeepanCode.
Implements the exact same token tracking model as OpenCode:
- 5 token types: input, output, reasoning, cache.read, cache.write
- Per-message and per-session cost calculation
- Tiered pricing based on context size
- Provider-specific cache token detection
"""

import json
import os
import time
from decimal import Decimal
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict


@dataclass
class TokenBreakdown:
    """Token breakdown matching OpenCode's structure."""
    input: float = 0.0
    output: float = 0.0
    reasoning: float = 0.0
    cache_read: float = 0.0
    cache_write: float = 0.0

    @property
    def total(self) -> float:
        return self.input + self.output + self.reasoning + self.cache_read + self.cache_write

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input": self.input,
            "output": self.output,
            "reasoning": self.reasoning,
            "cache": {
                "read": self.cache_read,
                "write": self.cache_write
            }
        }


@dataclass
class CostInfo:
    """Cost per 1M tokens for different token types."""
    input: float = 0.0
    output: float = 0.0
    cache_read: float = 0.0
    cache_write: float = 0.0
    tiers: Optional[List[Dict[str, Any]]] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "input": self.input,
            "output": self.output,
            "cache": {
                "read": self.cache_read,
                "write": self.cache_write
            }
        }
        if self.tiers:
            result["tiers"] = self.tiers
        return result


@dataclass
class MessageUsage:
    """Token usage for a single message."""
    message_id: str
    timestamp: float
    tokens: TokenBreakdown
    cost: float
    model_id: str
    provider_id: str
    context_tokens: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "timestamp": self.timestamp,
            "tokens": self.tokens.to_dict(),
            "cost": self.cost,
            "model_id": self.model_id,
            "provider_id": self.provider_id,
            "context_tokens": self.context_tokens
        }


@dataclass
class SessionUsage:
    """Aggregated token usage for a session."""
    session_id: str
    messages: List[MessageUsage] = field(default_factory=list)
    total_tokens: TokenBreakdown = field(default_factory=TokenBreakdown)
    total_cost: float = 0.0
    start_time: float = field(default_factory=time.time)

    def add_message(self, usage: MessageUsage):
        self.messages.append(usage)
        self.total_tokens.input += usage.tokens.input
        self.total_tokens.output += usage.tokens.output
        self.total_tokens.reasoning += usage.tokens.reasoning
        self.total_tokens.cache_read += usage.tokens.cache_read
        self.total_tokens.cache_write += usage.tokens.cache_write
        self.total_cost += usage.cost

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "total_tokens": self.total_tokens.to_dict(),
            "total_cost": self.total_cost,
            "message_count": len(self.messages),
            "duration_seconds": time.time() - self.start_time,
            "messages": [m.to_dict() for m in self.messages[-10:]]
        }


def safe_number(value: Any) -> float:
    """Safe number conversion matching OpenCode's safe() function."""
    if value is None:
        return 0.0
    try:
        v = float(value)
        if not (v == v):  # NaN check
            return 0.0
        if v < 0:
            return 0.0
        return v
    except (ValueError, TypeError):
        return 0.0


def get_cache_tokens(provider_metadata: Dict[str, Any]) -> tuple:
    """
    Extract cache tokens from provider-specific metadata.
    Matches OpenCode's provider-specific cache detection.
    """
    cache_read = 0
    cache_write = 0

    def _section(meta, key):
        node = meta.get(key, {})
        return node if isinstance(node, dict) else {}

    # Anthropic: cache_creation (write) + cache_read_input_tokens (read)
    if "anthropic" in provider_metadata:
        node = _section(provider_metadata, "anthropic")
        cache_write = node.get("cacheCreationInputTokens", 0)
        cache_read = node.get("cacheReadInputTokens", 0)

    # Vertex: metadata.vertex.cacheCreationInputTokens / cacheReadInputTokens
    if "vertex" in provider_metadata:
        node = _section(provider_metadata, "vertex")
        cache_write = node.get("cacheCreationInputTokens", 0)
        cache_read = node.get("cacheReadInputTokens", cache_read)

    # Bedrock: metadata.bedrock.usage.cacheWriteInputTokens / cacheReadInputTokens
    if "bedrock" in provider_metadata:
        usage = _section(_section(provider_metadata, "bedrock"), "usage")
        cache_write = usage.get("cacheWriteInputTokens", 0)
        cache_read = usage.get("cacheReadInputTokens", cache_read)

    # Venice: metadata.venice.usage.cacheCreationInputTokens / cacheReadInputTokens
    if "venice" in provider_metadata:
        usage = _section(_section(provider_metadata, "venice"), "usage")
        cache_write = usage.get("cacheCreationInputTokens", 0)
        cache_read = usage.get("cacheReadInputTokens", cache_read)

    return safe_number(cache_read), safe_number(cache_write)


def calculate_cost(
    tokens: TokenBreakdown,
    cost_info: CostInfo,
    context_tokens: int = 0
) -> float:
    """
    Calculate cost matching OpenCode's exact formula:
    cost = (input × inputPrice / 1,000,000)
         + (output × outputPrice / 1,000,000)
         + (cache.read × cacheReadPrice / 1,000,000)
         + (cache.write × cacheWritePrice / 1,000,000)
         + (reasoning × outputPrice / 1,000,000)  # reasoning charged at output rate
    """
    # Check for tiered pricing based on context size
    effective_cost = cost_info
    if cost_info.tiers and context_tokens > 0:
        # Find the highest tier that applies
        applicable_tiers = [
            tier for tier in cost_info.tiers
            if tier.get("tier", {}).get("type") == "context"
            and context_tokens > tier.get("tier", {}).get("size", 0)
        ]
        if applicable_tiers:
            # Use the tier with the largest size threshold
            best_tier = max(applicable_tiers, key=lambda t: t.get("tier", {}).get("size", 0))
            effective_cost = CostInfo(
                input=best_tier.get("input", cost_info.input),
                output=best_tier.get("output", cost_info.output),
                cache_read=best_tier.get("cache", {}).get("read", cost_info.cache_read),
                cache_write=best_tier.get("cache", {}).get("write", cost_info.cache_write)
            )

    cost = (
        Decimal(str(tokens.input)) * Decimal(str(effective_cost.input)) / Decimal("1000000")
        + Decimal(str(tokens.output)) * Decimal(str(effective_cost.output)) / Decimal("1000000")
        + Decimal(str(tokens.cache_read)) * Decimal(str(effective_cost.cache_read)) / Decimal("1000000")
        + Decimal(str(tokens.cache_write)) * Decimal(str(effective_cost.cache_write)) / Decimal("1000000")
        + Decimal(str(tokens.reasoning)) * Decimal(str(effective_cost.output)) / Decimal("1000000")
    )

    return float(cost)


def get_usage_from_response(
    response: Dict[str, Any],
    model_id: str,
    provider_id: str,
    cost_info: CostInfo,
    provider_metadata: Optional[Dict[str, Any]] = None
) -> MessageUsage:
    """
    Extract token usage from an API response matching OpenCode's getUsage function.

    Handles provider-specific token counting:
    - OpenAI: prompt_tokens, completion_tokens, total_tokens
    - Anthropic: input_tokens, output_tokens, cache_creation_input_tokens
    - Generic: prompt_tokens, completion_tokens
    """
    usage = response.get("usage", {})
    metadata = provider_metadata or response.get("provider_metadata", {})

    # Get raw token counts
    input_tokens = safe_number(
        usage.get("prompt_tokens")
        or usage.get("input_tokens")
        or usage.get("total_tokens", 0) - usage.get("completion_tokens", 0)
    )

    output_tokens = safe_number(
        usage.get("completion_tokens")
        or usage.get("output_tokens")
    )

    reasoning_tokens = safe_number(
        usage.get("reasoning_tokens")
        or usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0)
    )

    # Get cache tokens from provider-specific metadata
    cache_read, cache_write = get_cache_tokens(metadata)

    # Also check usage object directly for cache tokens
    if not cache_read:
        cache_read = safe_number(usage.get("cache_read_input_tokens", 0))
    if not cache_write:
        cache_write = safe_number(
            usage.get("cache_creation_input_tokens", 0)
            or usage.get("cache_write_input_tokens", 0)
        )

    # Adjust input tokens to exclude cache tokens (matching OpenCode)
    # AI SDK v6 normalized inputTokens to include cached tokens
    adjusted_input = max(0, input_tokens - cache_read - cache_write)

    # Build token breakdown
    tokens = TokenBreakdown(
        input=adjusted_input,
        output=max(0, output_tokens - reasoning_tokens),
        reasoning=reasoning_tokens,
        cache_read=cache_read,
        cache_write=cache_write
    )

    # Calculate cost
    context_tokens = int(input_tokens)
    cost = calculate_cost(tokens, cost_info, context_tokens)

    return MessageUsage(
        message_id=response.get("id", f"msg_{int(time.time() * 1000)}"),
        timestamp=time.time(),
        tokens=tokens,
        cost=cost,
        model_id=model_id,
        provider_id=provider_id,
        context_tokens=context_tokens
    )


class TokenUsageTracker:
    """Main token usage tracker for the agent."""

    def __init__(self):
        self.sessions: Dict[str, SessionUsage] = {}
        self.current_session_id: Optional[str] = None
        self.current_session: Optional[SessionUsage] = None
        self._load_state()

    def _get_state_path(self) -> str:
        """Get path to state file."""
        config_dir = os.path.join(os.path.expanduser("~"), ".config", "deepans_code")
        os.makedirs(config_dir, exist_ok=True)
        return os.path.join(config_dir, "token_usage.json")

    def _load_state(self):
        """Load persisted state from disk."""
        try:
            state_path = self._get_state_path()
            if os.path.exists(state_path):
                with open(state_path, "r") as f:
                    state = json.load(f)
                # Restore sessions (simplified - in production you'd use proper deserialization)
                for sid, data in state.get("sessions", {}).items():
                    session = SessionUsage(session_id=sid, start_time=data.get("start_time", time.time()))
                    session.total_cost = data.get("total_cost", 0)
                    self.sessions[sid] = session
        except Exception:
            pass

    def _save_state(self):
        """Persist state to disk."""
        try:
            state_path = self._get_state_path()
            state = {
                "sessions": {
                    sid: {
                        "total_cost": s.total_cost,
                        "start_time": s.start_time,
                        "message_count": len(s.messages)
                    }
                    for sid, s in self.sessions.items()
                },
                "last_updated": time.time()
            }
            with open(state_path, "w") as f:
                json.dump(state, f, indent=2)
        except Exception:
            pass

    def start_session(self, session_id: str) -> SessionUsage:
        """Start a new tracking session."""
        self.current_session_id = session_id
        self.current_session = SessionUsage(session_id=session_id)
        self.sessions[session_id] = self.current_session
        return self.current_session

    def track_message(
        self,
        response: Dict[str, Any],
        model_id: str,
        provider_id: str,
        cost_info: CostInfo,
        provider_metadata: Optional[Dict[str, Any]] = None
    ) -> MessageUsage:
        """Track token usage for a single message."""
        if not self.current_session:
            self.start_session(f"session_{int(time.time() * 1000)}")

        usage = get_usage_from_response(
            response, model_id, provider_id, cost_info, provider_metadata
        )
        self.current_session.add_message(usage)
        self._save_state()
        return usage

    def get_session_summary(self) -> Dict[str, Any]:
        """Get summary of current session."""
        if not self.current_session:
            return {}
        return self.current_session.to_dict()

    def get_global_summary(self) -> Dict[str, Any]:
        """Get summary across all sessions."""
        total_tokens = TokenBreakdown()
        total_cost = 0.0
        total_messages = 0

        for session in self.sessions.values():
            total_tokens.input += session.total_tokens.input
            total_tokens.output += session.total_tokens.output
            total_tokens.reasoning += session.total_tokens.reasoning
            total_tokens.cache_read += session.total_tokens.cache_read
            total_tokens.cache_write += session.total_tokens.cache_write
            total_cost += session.total_cost
            total_messages += len(session.messages)

        return {
            "total_tokens": total_tokens.to_dict(),
            "total_cost": total_cost,
            "total_sessions": len(self.sessions),
            "total_messages": total_messages
        }


# Singleton instance
token_tracker = TokenUsageTracker()
