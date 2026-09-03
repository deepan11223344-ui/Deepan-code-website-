"""
Async tool executor for DeepanCode.
Runs multiple tools in parallel using concurrent.futures.
"""

import concurrent.futures
import logging
from typing import List, Dict, Any, Tuple

logger = logging.getLogger("deepans_code.async_executor")

_executor = None


def get_executor():
    global _executor
    if _executor is None:
        _executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
    return _executor


def execute_tools_parallel(tool_calls: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    from deepans_code.tools import execute_tool
    results = []
    futures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        for tc in tool_calls:
            if isinstance(tc, dict) and "function" in tc:
                fn_name = tc["function"].get("name", "")
                fn_args_str = tc["function"].get("arguments", "{}")
                call_id = tc.get("id", "")
                import json
                try:
                    fn_args = json.loads(fn_args_str) if isinstance(fn_args_str, str) else fn_args_str
                except Exception:
                    fn_args = {}
                futures.append((call_id, fn_name, executor.submit(execute_tool, fn_name, fn_args)))
        for call_id, fn_name, future in futures:
            try:
                result = future.result(timeout=30)
                results.append((call_id, result))
            except concurrent.futures.TimeoutError:
                results.append((call_id, f"Error: Tool '{fn_name}' timed out after 30s"))
            except Exception as e:
                results.append((call_id, f"Error executing {fn_name}: {str(e)}"))
    return results


def shutdown_executor():
    global _executor
    if _executor:
        _executor.shutdown(wait=False)
        _executor = None
