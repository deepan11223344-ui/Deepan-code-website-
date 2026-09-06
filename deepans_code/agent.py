"""
Core Agentic Loop for DeepanCode.
Handles conversation management, system prompt injection, tool calling pipeline,
anti-hallucination verification, and multi-turn autonomous execution.
Includes persistence, token enforcement, input sanitization, error recovery, and logging.
"""

import os
import re
import json
import time
import logging
from typing import List, Dict, Any, Tuple, Optional, Generator
from deepans_code.config import config_mgr
from deepans_code.system_prompt import generate_system_prompt
from deepans_code.tools import get_tool_schemas, execute_tool, execute_tools_parallel
from deepans_code.client import client
from deepans_code.models import get_model_cost, get_model_context_window, is_model_valid_for_provider, get_default_model_for_provider
from deepans_code.security import InputSanitizer, rate_limiter
from deepans_code.database import db
from deepans_code.error_recovery import error_handler, retry_with_backoff
from deepans_code.cache import response_cache
from deepans_code.token_usage import (
    TokenUsageTracker, TokenBreakdown, MessageUsage, SessionUsage,
    token_tracker, safe_number
)

logger = logging.getLogger("deepans_code.agent")
sanitizer = InputSanitizer()

MAX_SESSION_TOKENS = 2_000_000
MAX_CONSECUTIVE_ERRORS = 5
MAX_TOOL_OUTPUT_CHARS = 12000
MAX_HISTORY_MESSAGES = 20  # system + last N; prevents context-window overflow


class Agent:
    def __init__(self, conversation_id=None, database=None):
        self.messages = []
        self.total_tokens_used = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.last_response_time = 0.0
        self.last_token_usage = {}
        self.last_request_tokens = 0
        self.last_request_prompt = 0
        self.last_request_completion = 0
        self.token_breakdown = TokenBreakdown()
        self.session_cost = 0.0
        self.message_usages: List[MessageUsage] = []
        self.current_model_id = ""
        self.current_provider_id = ""
        self.conversation_id = conversation_id
        self.database = database or db
        self.consecutive_errors = 0
        self._inject_system_prompt()
        if conversation_id:
            self._load_conversation(conversation_id)

    def _load_conversation(self, conv_id):
        messages = self.database.get_messages(conv_id)
        if messages:
            self.messages = []
            for m in messages:
                entry = {"role": m["role"], "content": m["content"]}
                if m.get("tool_calls"):
                    entry["tool_calls"] = m["tool_calls"]
                if m.get("tool_call_id"):
                    entry["tool_call_id"] = m["tool_call_id"]
                self.messages.append(entry)
            if not self.messages or self.messages[0].get("role") != "system":
                self._inject_system_prompt()
            logger.info(f"Loaded conversation {conv_id}: {len(messages)} messages")

    def _save_message(self, role, content, tool_calls=None, tool_call_id=None):
        if not self.conversation_id:
            model = config_mgr.get("model", "")
            provider = config_mgr.get("provider", "")
            mode = config_mgr.get("mode", "code")
            self.conversation_id = self.database.create_conversation(model=model, provider=provider, mode=mode)
        self.database.save_message(self.conversation_id, role, content, tool_calls, tool_call_id)

    @staticmethod
    def _sanitize(text):
        """Strip control characters but preserve Unicode/code/markdown."""
        if not text:
            return text
        # Keep printable Unicode; drop C0/C1 controls except TAB/LF/CR.
        cleaned = "".join(
            ch for ch in text
            if ch in ("\t", "\n", "\r") or (ord(ch) >= 32 and ord(ch) != 127)
        )
        # Collapse runs of blank lines / trailing spaces without
        # destroying intentional indentation.
        lines = [ln.rstrip() for ln in cleaned.split("\n")]
        collapsed: list = []
        blank_run = 0
        for ln in lines:
            if ln.strip() == "":
                blank_run += 1
                if blank_run <= 2:
                    collapsed.append("")
                continue
            blank_run = 0
            collapsed.append(ln)
        return "\n".join(collapsed).strip("\n")

    @staticmethod
    def _sanitize_tool_calls(tool_calls):
        """Validate tool-call payloads fail-loud instead of hiding errors."""
        if not tool_calls:
            return tool_calls
        if not isinstance(tool_calls, list):
            logger.warning("Dropping tool calls: expected list, got %s", type(tool_calls).__name__)
            return []
        cleaned = []
        for tc in tool_calls:
            if not isinstance(tc, dict):
                logger.warning("Dropping malformed tool call (not a dict): %r", tc)
                continue
            if "function" not in tc or not isinstance(tc["function"], dict):
                logger.warning("Dropping tool call without a valid 'function': %r", tc)
                continue
            fn = tc["function"]
            args_str = fn.get("arguments", "{}")
            if isinstance(args_str, str):
                try:
                    parsed = json.loads(args_str) if args_str.strip() else {}
                    fn["arguments"] = json.dumps(parsed, ensure_ascii=False)
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(
                        "Dropping tool call '%s' with invalid JSON arguments: %s",
                        fn.get("name"), e,
                    )
                    continue
            elif isinstance(args_str, dict):
                fn["arguments"] = json.dumps(args_str, ensure_ascii=False)
            else:
                logger.warning(
                    "Dropping tool call '%s': arguments must be JSON string or dict",
                    fn.get("name"),
                )
                continue
            cleaned.append(tc)
        return cleaned

    def reset_conversation(self):
        if self.conversation_id:
            logger.info(f"Resetting conversation {self.conversation_id}")
        self.messages = []
        self.total_tokens_used = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.last_response_time = 0.0
        self.last_token_usage = {}
        self.last_request_tokens = 0
        self.last_request_prompt = 0
        self.last_request_completion = 0
        self.token_breakdown = TokenBreakdown()
        self.session_cost = 0.0
        self.message_usages = []
        self.conversation_id = None
        self._inject_system_prompt()

    def get_token_usage(self):
        model_id = config_mgr.get("model", "")
        provider_id = config_mgr.get("provider", "")
        context_window = get_model_context_window(model_id)
        used = self.token_breakdown.total
        percentage = min((used / context_window * 100), 100) if context_window > 0 else 0
        return {
            "last_request_tokens": self.last_request_tokens,
            "last_request_prompt": self.last_request_prompt,
            "last_request_completion": self.last_request_completion,
            "total_used": used,
            "total_prompt": self.total_prompt_tokens,
            "total_completion": self.total_completion_tokens,
            "context_window": context_window,
            "percentage": percentage,
            "response_time": self.last_response_time,
            "tokens": self.token_breakdown.to_dict(),
            "cost": self.session_cost,
            "model_id": model_id,
            "provider_id": provider_id,
            "message_count": len(self.message_usages)
        }

    def get_usage_summary(self) -> Dict[str, Any]:
        return token_tracker.get_session_summary()

    def _ensure_valid_model(self):
        model = config_mgr.get("model", "openrouter/free")
        provider = config_mgr.get("provider", "openrouter")
        if not is_model_valid_for_provider(model, provider):
            new_model = get_default_model_for_provider(provider)
            logger.warning(f"Model '{model}' invalid for '{provider}'; switching to '{new_model}'")
            config_mgr.set("model", new_model)

    def _truncate_history(self):
        """Keep system prompt + last N messages to avoid context overflow."""
        if len(self.messages) <= MAX_HISTORY_MESSAGES:
            return
        system = [m for m in self.messages if m.get("role") == "system"][:1]
        rest = [m for m in self.messages if m.get("role") != "system"]
        self.messages = system + rest[-(MAX_HISTORY_MESSAGES - len(system)):]

    @staticmethod
    def _sanitize_tool_output(text: str) -> str:
        if not text:
            return ""
        cleaned = Agent._sanitize(text)
        if len(cleaned) > MAX_TOOL_OUTPUT_CHARS:
            cleaned = cleaned[:MAX_TOOL_OUTPUT_CHARS] + f"\n\n... (truncated {len(cleaned) - MAX_TOOL_OUTPUT_CHARS} chars)"
        return cleaned

    @staticmethod
    def _extract_thinking(content: str):
        """Single shared think-strip helper (was duplicated in both loops)."""
        think_match = re.search(r"<think>(.*?)</think>", content, re.DOTALL)
        if think_match:
            thinking = think_match.group(1).strip()
            clean = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
            return thinking, clean
        if "<think>" in content:
            parts = content.split("<think>", 1)
            return parts[1].strip(), parts[0].strip()
        return "", content

    def _check_token_budget(self) -> bool:
        if self.token_breakdown.total > MAX_SESSION_TOKENS:
            logger.warning(f"Session token budget exceeded: {self.token_breakdown.total}/{MAX_SESSION_TOKENS}")
            return False
        return True

    def _prepare_user_turn(self, user_input: str) -> str:
        """Shared prep for both loops: validate model, refresh prompt, truncate, append+save."""
        self._ensure_valid_model()
        self._inject_system_prompt()
        self._truncate_history()
        sanitized = sanitizer.sanitize(user_input, strict=True)
        self.messages.append({"role": "user", "content": sanitized})
        self._save_message("user", sanitized)
        return sanitized

    @staticmethod
    def _coerce_call_id(raw, default_id: str) -> str:
        if isinstance(raw, str) and raw.strip():
            return raw.strip()[:128]
        if isinstance(raw, int) and raw >= 0:
            return str(raw)
        return default_id

    @staticmethod
    def _parse_single_tool_call(tc: dict, default_id: str):
        """Shared tool-call arg parsing. Returns (fn_name, fn_args, call_id) or None."""
        if isinstance(tc, dict) and isinstance(tc.get("function"), dict):
            fn_name = tc["function"].get("name", "")
            fn_args_str = tc["function"].get("arguments", "{}")
            call_id = Agent._coerce_call_id(tc.get("id"), default_id)
            try:
                fn_args = json.loads(fn_args_str) if isinstance(fn_args_str, str) else fn_args_str
                if not isinstance(fn_args, dict):
                    logger.warning(f"Tool '{fn_name}' args not a dict; dropping call")
                    return None
            except (json.JSONDecodeError, ValueError, TypeError) as e:
                logger.warning(f"Tool '{fn_name}' invalid JSON args, dropping call: {e}")
                return None
            return fn_name, fn_args, call_id
        if isinstance(tc, dict) and "name" in tc:
            fn_name = tc["name"]
            fn_args = tc.get("arguments", {})
            if not isinstance(fn_args, dict):
                logger.warning(f"Tool '{fn_name}' args not a dict; dropping call")
                return None
            return fn_name, fn_args, Agent._coerce_call_id(tc.get("id"), default_id)
        return None

    def _append_tool_result(self, call_id: str, fn_name: str, result: str) -> str:
        """Shared: sanitise + save + append tool result. Returns preview string."""
        result = self._sanitize_tool_output(result)
        self._save_message("tool", result, tool_call_id=call_id)
        self.messages.append({
            "role": "tool",
            "tool_call_id": call_id,
            "name": fn_name,
            "content": result,
        })
        return result if len(result) < 500 else result[:497] + "..."

    def _record_stream_usage(self, response_chunks, usage) -> None:
        """Shared streaming usage accounting (deduped from send_message_stream)."""
        if not isinstance(usage, dict):
            usage = {}
        if not isinstance(response_chunks, list):
            response_chunks = []
        model_id = config_mgr.get("model", "")
        provider_id = config_mgr.get("provider", "")
        if response_chunks and not usage:
            usage_msg = client.extract_streaming_token_usage(response_chunks, model_id, provider_id)
            if usage_msg:
                self._apply_usage_msg(usage_msg)
        elif usage:
            usage_msg = client.extract_token_usage({"usage": usage}, model_id, provider_id)
            if usage_msg:
                self._apply_usage_msg(usage_msg)
            self.last_request_tokens = usage.get("total_tokens", 0)
            self.last_request_prompt = usage.get("prompt_tokens", 0)
            self.last_request_completion = usage.get("completion_tokens", 0)

    def _apply_usage_msg(self, usage_msg) -> None:
        self.token_breakdown.input += usage_msg.tokens.input
        self.token_breakdown.output += usage_msg.tokens.output
        self.token_breakdown.reasoning += usage_msg.tokens.reasoning
        self.token_breakdown.cache_read += usage_msg.tokens.cache_read
        self.token_breakdown.cache_write += usage_msg.tokens.cache_write
        self.session_cost += usage_msg.cost
        self.message_usages.append(usage_msg)
        self.total_prompt_tokens += usage_msg.tokens.input
        self.total_completion_tokens += usage_msg.tokens.output
        self.total_tokens_used += usage_msg.tokens.total
        self.last_request_tokens = usage_msg.tokens.total
        self.last_request_prompt = usage_msg.tokens.input
        self.last_request_completion = usage_msg.tokens.output

    def _inject_system_prompt(self):
        model_id = config_mgr.get("model", "openrouter/free")
        mode = config_mgr.get("mode", "code")
        effort = config_mgr.get("effort", "medium")
        agent_type = config_mgr.get("agent", "build")
        os_type = "windows" if os.name == "nt" else "linux"
        from deepans_code.skill_manager import skill_mgr
        enabled_skills_content = skill_mgr.get_enabled_skills_content()
        sys_prompt = generate_system_prompt(
            model_id=model_id, mode=mode, effort=effort,
            os_type=os_type, agent_type=agent_type,
            enabled_skills_content=enabled_skills_content
        )
        if self.messages and self.messages[0]["role"] == "system":
            self.messages[0]["content"] = sys_prompt
        else:
            self.messages.insert(0, {"role": "system", "content": sys_prompt})

    def _track_usage(self, response: Dict[str, Any]) -> Optional[MessageUsage]:
        model_id = config_mgr.get("model", "")
        provider_id = config_mgr.get("provider", "")
        self.current_model_id = model_id
        self.current_provider_id = provider_id
        usage_msg = client.extract_token_usage(response, model_id, provider_id)
        usage = response.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}
        self.total_prompt_tokens += usage.get("prompt_tokens", 0)
        self.total_completion_tokens += usage.get("completion_tokens", 0)
        self.total_tokens_used += usage.get("total_tokens", 0)
        self.last_token_usage = usage
        self.last_request_tokens = usage.get("total_tokens", 0)
        self.last_request_prompt = usage.get("prompt_tokens", 0)
        self.last_request_completion = usage.get("completion_tokens", 0)
        if usage_msg:
            self.token_breakdown.input += usage_msg.tokens.input
            self.token_breakdown.output += usage_msg.tokens.output
            self.token_breakdown.reasoning += usage_msg.tokens.reasoning
            self.token_breakdown.cache_read += usage_msg.tokens.cache_read
            self.token_breakdown.cache_write += usage_msg.tokens.cache_write
            self.session_cost += usage_msg.cost
            self.message_usages.append(usage_msg)
            config_mgr.track_token_usage(usage_msg.tokens.total)
        return usage_msg

    def send_message_stream(self, user_input):
        if not self._check_token_budget():
            yield ("error", "Session token budget exceeded. Use /clear to start fresh.")
            return
        # Strict injection gate: block before any LLM/history side-effect.
        detected, reason = sanitizer.detect_injection(user_input or "")
        if detected:
            logger.warning(f"Blocked prompt-injection input: {reason}")
            yield ("error", f"Security: prompt-injection pattern blocked ({reason[:120]}). Rephrase and retry.")
            return
        sanitized = sanitizer.sanitize(user_input, strict=True)
        self._prepare_user_turn(sanitized)
        max_turns = 3
        current_turn = 0
        tools = get_tool_schemas()
        show_thinking = config_mgr.get("thinking", True)
        start_time = time.time()
        while current_turn < max_turns:
            current_turn += 1
            full_content = ""
            tool_calls_raw = []
            usage = {}
            response_chunks = []
            try:
                in_think_block = False
                think_buffer = ""
                content_buffer = ""
                for chunk in client.chat_completion_stream(self.messages, tools=tools):
                    if not isinstance(chunk, dict):
                        continue
                    response_chunks.append(chunk)
                    if isinstance(chunk.get("usage"), dict):
                        usage = chunk["usage"]
                    choices = chunk.get("choices", [])
                    if not isinstance(choices, list) or not choices:
                        continue
                    first = choices[0] if isinstance(choices[0], dict) else {}
                    delta = first.get("delta", {})
                    if not isinstance(delta, dict):
                        continue
                    if delta.get("tool_calls"):
                        for tc_delta in delta["tool_calls"]:
                            idx = tc_delta.get("index", 0)
                            while len(tool_calls_raw) <= idx:
                                tool_calls_raw.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                            tc = tool_calls_raw[idx]
                            if tc_delta.get("id"):
                                tc["id"] = tc_delta["id"]
                            fn = tc_delta.get("function", {})
                            if fn.get("name"):
                                tc["function"]["name"] += fn["name"]
                            if fn.get("arguments"):
                                tc["function"]["arguments"] += fn["arguments"]
                    token = delta.get("content") or ""
                    if not token:
                        continue
                    full_content += token
                    if show_thinking:
                        temp = content_buffer + token
                        content_buffer = temp
                        if not in_think_block and "<think>" in content_buffer:
                            pre, _, rest = content_buffer.partition("<think>")
                            content_buffer = rest
                            in_think_block = True
                        if in_think_block:
                            if "</think>" in content_buffer:
                                think_part, _, after = content_buffer.partition("</think>")
                                think_buffer += think_part
                                content_buffer = after
                                in_think_block = False
                                if think_buffer.strip():
                                    yield ("thinking_done", self._sanitize(think_buffer.strip()))
                                    think_buffer = ""
                            else:
                                if token and not token.startswith("<"):
                                    think_buffer += token
                                    yield ("thinking_chunk", self._sanitize(token))
            except Exception as e:
                logger.error(f"Streaming error: {e}")
                self.consecutive_errors += 1
                if self.consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    yield ("error", "Too many consecutive errors. Try /clear and start fresh.")
                    break
                try:
                    response = client.chat_completion(self.messages, tools=tools)
                    self._track_usage(response)
                    self.consecutive_errors = 0
                    choices = response.get("choices", [])
                    if not isinstance(choices, list) or not choices:
                        yield ("error", "Empty response from LLM.")
                        break
                    msg = choices[0] if isinstance(choices[0], dict) else {}
                    msg = msg.get("message", {})
                    if not isinstance(msg, dict):
                        msg = {}
                    full_content = msg.get("content") or ""
                    tool_calls_raw = msg.get("tool_calls", []) or []
                except Exception as e2:
                    error_msg = error_handler.handle_api_error(
                        config_mgr.get("provider", "openrouter"), 0
                    )
                    yield ("error", error_msg)
                    break
            self._record_stream_usage(response_chunks, usage)
            thinking_content, clean_content = self._extract_thinking(full_content)
            self.consecutive_errors = 0  # success resets the streak
            if not tool_calls_raw and "<tool_call>" in clean_content:
                tool_calls_raw = self._parse_xml_tool_calls(clean_content)
            tool_calls_raw = self._sanitize_tool_calls(tool_calls_raw)
            assistant_msg = {"role": "assistant"}
            if clean_content:
                assistant_msg["content"] = clean_content
            if tool_calls_raw:
                assistant_msg["tool_calls"] = tool_calls_raw
            self.messages.append(assistant_msg)
            self._save_message("assistant", clean_content, tool_calls_raw if tool_calls_raw else None)
            if not tool_calls_raw:
                if clean_content:
                    yield ("assistant", self._sanitize(clean_content))
                elif not thinking_content:
                    yield ("assistant", "[Task completed]")
                break
            # Execute tools - parallel if multiple independent calls
            if len(tool_calls_raw) > 1:
                # Parallel execution for multiple tools
                yield ("status", f"Executing {len(tool_calls_raw)} tools in parallel...")
                parallel_results = execute_tools_parallel(tool_calls_raw)
                for call_id, result in parallel_results:
                    # Find the matching tool call for preview
                    fn_name = "unknown"
                    for tc in tool_calls_raw:
                        if tc.get("id") == call_id:
                            if "function" in tc:
                                fn_name = tc["function"].get("name", "")
                            break
                    res_preview = self._append_tool_result(call_id, fn_name, result)
                    yield ("tool_result", self._sanitize(res_preview))
            else:
                # Single tool execution (shared parser)
                for idx, tc in enumerate(tool_calls_raw):
                    parsed = self._parse_single_tool_call(tc, f"call_{current_turn}_{idx}")
                    if parsed is None:
                        continue
                    fn_name, fn_args, call_id = parsed
                    args_preview = json.dumps(fn_args, ensure_ascii=False)
                    if len(args_preview) > 100:
                        args_preview = args_preview[:97] + "..."
                    yield ("tool_call", self._sanitize(f"{fn_name}({args_preview})"))
                    result = execute_tool(fn_name, fn_args)
                    res_preview = self._append_tool_result(call_id, fn_name, result)
                    yield ("tool_result", self._sanitize(res_preview))
        self.last_response_time = time.time() - start_time
        try:
            from deepans_code.metrics import metrics
            metrics.record_request(
                config_mgr.get("provider", ""),
                self.last_response_time,
                True,
                self.last_request_tokens
            )
        except ImportError:
            pass
        config_mgr.save()

    def _record_completion(self) -> None:
        self.last_response_time = 0  # set by caller; kept for symmetry
        config_mgr.save()

    def send_message(self, user_input, status_callback=None):
        if not self._check_token_budget():
            return [("error", "Session token budget exceeded. Use /clear to start fresh.")]
        detected, reason = sanitizer.detect_injection(user_input or "")
        output_steps = []
        if detected:
            logger.warning(f"Blocked prompt-injection input: {reason}")
            return [("error", f"Security: prompt-injection pattern blocked ({reason[:120]}). Rephrase and retry.")]
        sanitized = sanitizer.sanitize(user_input, strict=True)
        self._prepare_user_turn(sanitized)
        max_turns = 3
        current_turn = 0
        tools = get_tool_schemas()
        start_time = time.time()
        while current_turn < max_turns:
            current_turn += 1
            self._truncate_history()
            if status_callback:
                status_callback("")
            try:
                response = client.chat_completion(self.messages, tools=tools)
                self._track_usage(response)
            except Exception as e:
                error_msg = str(e)
                if "401" in error_msg or "403" in error_msg:
                    output_steps.append(("error", f"Authentication failed. Run: /connect openrouter <YOUR_KEY>"))
                elif "400" in error_msg:
                    output_steps.append(("error", f"Bad request. Try: /config model openrouter/free"))
                else:
                    output_steps.append(("error", f"API error: {error_msg[:200]}"))
                break
            choices = response.get("choices", [])
            if not isinstance(choices, list) or not choices:
                output_steps.append(("error", "Empty response received from LLM model."))
                break
            msg = choices[0] if isinstance(choices[0], dict) else {}
            msg = msg.get("message", {})
            if not isinstance(msg, dict):
                msg = {}
            content = msg.get("content") or ""
            tool_calls = msg.get("tool_calls", []) or []
            thinking_content, clean_content = self._extract_thinking(content)
            if thinking_content and config_mgr.get("thinking", True):
                output_steps.append(("thinking", thinking_content))
            if not tool_calls and "<tool_call>" in clean_content:
                tool_calls = self._parse_xml_tool_calls(clean_content)
            tool_calls = self._sanitize_tool_calls(tool_calls)
            assistant_msg = {"role": "assistant"}
            if clean_content:
                assistant_msg["content"] = clean_content
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            self.messages.append(assistant_msg)
            self._save_message("assistant", clean_content, tool_calls if tool_calls else None)
            if clean_content and not tool_calls:
                output_steps.append(("assistant", self._sanitize(clean_content)))
                break
            if not tool_calls:
                if not clean_content and not thinking_content:
                    output_steps.append(("assistant", "[Task completed]"))
                break
            for idx, tc in enumerate(tool_calls):
                parsed = self._parse_single_tool_call(tc, f"call_{current_turn}_{idx}")
                if parsed is None:
                    continue
                fn_name, fn_args, call_id = parsed
                if status_callback:
                    status_callback(f"Executing tool: {fn_name}...")
                args_preview = json.dumps(fn_args, ensure_ascii=False)
                if len(args_preview) > 100:
                    args_preview = args_preview[:97] + "..."
                output_steps.append(("tool_call", self._sanitize(f"{fn_name}({args_preview})")))
                result = execute_tool(fn_name, fn_args)
                res_preview = self._append_tool_result(call_id, fn_name, result)
                output_steps.append(("tool_result", self._sanitize(res_preview)))
        self.last_response_time = time.time() - start_time
        config_mgr.save()
        return output_steps

    def _parse_xml_tool_calls(self, text):
        calls = []
        matches = re.findall(r"<tool_call>(.*?)</tool_call>", text, re.DOTALL)
        for idx, m in enumerate(matches):
            try:
                data = json.loads(m.strip())
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Ignoring malformed <tool_call> #{idx}: {e}")
                continue
            name = data.get("name") if isinstance(data, dict) else None
            if not name:
                logger.warning(f"Ignoring <tool_call> #{idx} without a name")
                continue
            args = data.get("arguments", {}) if isinstance(data, dict) else {}
            calls.append({
                "id": f"xml_call_{idx}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(args if isinstance(args, dict) else {})
                }
            })
        return calls


# Lazy singleton: avoids filesystem side-effects (config dirs, sqlite init,
# skill loading) at import time so `import deepans_code.agent` is safe in
# tests and fresh environments.
agent_instance = None


def get_agent(conversation_id=None):
    """Return the shared Agent instance, creating it on first use."""
    global agent_instance
    if agent_instance is None or conversation_id is not None:
        instance = Agent(conversation_id=conversation_id)
        if conversation_id is None:
            agent_instance = instance
        return instance
    return agent_instance
