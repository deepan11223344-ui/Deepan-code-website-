"""
Error recovery module for DeepanCode.
Provides automatic retries, circuit breaker, and graceful degradation.
"""

import random
import threading
import time
import logging
from typing import Callable, Any, Optional
from functools import wraps

logger = logging.getLogger("deepans_code.error_recovery")


class CircuitBreaker:
    def __init__(self, failure_threshold=5, recovery_timeout=60):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.last_failure_time = 0
        self.state = "closed"
        self._lock = threading.Lock()
        self._half_open_trial = False

    def record_failure(self):
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            self._half_open_trial = False
            if self.failure_count >= self.failure_threshold:
                self.state = "open"
                logger.warning(f"Circuit breaker opened after {self.failure_count} failures")

    def record_success(self):
        with self._lock:
            self.failure_count = 0
            self.state = "closed"
            self._half_open_trial = False

    def can_execute(self) -> bool:
        with self._lock:
            if self.state == "closed":
                return True
            if time.time() - self.last_failure_time > self.recovery_timeout:
                if self.state == "half-open" and self._half_open_trial:
                    return False  # single trial already in flight
                self.state = "half-open"
                self._half_open_trial = True
                return True
            return False


def retry_with_backoff(max_retries=3, base_delay=1.0, max_delay=30.0, exceptions=(Exception,)):
    max_retries = max(1, int(max_retries or 1))

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = min(base_delay * (2 ** attempt), max_delay) + random.uniform(0, 0.5)
                        logger.warning(f"Retry {attempt + 1}/{max_retries} after {delay:.1f}s: {e}")
                        time.sleep(delay)
            raise last_exception
        return wrapper
    return decorator


def safe_execute(func: Callable, *args, fallback=None, **kwargs) -> Any:
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logger.error(f"Safe execute failed: {e}", exc_info=True)
        return fallback


class ErrorHandler:
    def __init__(self):
        self.circuit_breakers = {}

    def get_breaker(self, name: str) -> CircuitBreaker:
        if name not in self.circuit_breakers:
            if len(self.circuit_breakers) > 100:
                oldest = next(iter(self.circuit_breakers))
                self.circuit_breakers.pop(oldest, None)
            self.circuit_breakers[name] = CircuitBreaker()
        return self.circuit_breakers[name]

    def record_success(self, name: str):
        self.get_breaker(name).record_success()

    def handle_tool_error(self, tool_name: str, error) -> str:
        breaker = self.get_breaker(tool_name)
        breaker.record_failure()
        error = str(error) if not isinstance(error, str) else error
        if "401" in error or "403" in error:
            return "Authentication failed. Check your API key with /connect"
        if "429" in error:
            return "Rate limited. Wait 60s or switch model with /model"
        if "timeout" in error.lower():
            return "Request timed out. Try a simpler task."
        if "connection" in error.lower():
            return "Connection failed. Check your internet."
        return f"Error: {error[:200]}"

    def handle_api_error(self, provider: str, status_code) -> str:
        breaker = self.get_breaker(provider)
        try:
            status_code = int(status_code)
        except (ValueError, TypeError):
            return f"API error ({status_code}) from {provider}"
        if status_code in (401, 403):
            breaker.record_failure()
            return f"Auth failed for {provider}. Run: /connect {provider} <key>"
        if status_code == 429:
            breaker.record_failure()
            return f"Rate limited by {provider}. Wait or switch provider."
        if status_code in (400, 404, 422):
            return f"Request error {status_code} from {provider}. Check model name with /model."
        if status_code >= 500:
            breaker.record_failure()
            return f"{provider} server error ({status_code}). Try again later."
        if status_code == 0:
            return f"Network error contacting {provider}. Check connection and retry."
        return f"API error {status_code} from {provider}"


error_handler = ErrorHandler()
