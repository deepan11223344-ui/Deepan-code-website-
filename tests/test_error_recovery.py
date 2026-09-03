"""Tests for error recovery module."""

import pytest
from deepans_code.error_recovery import (
    CircuitBreaker, retry_with_backoff, safe_execute, error_handler
)


class TestCircuitBreaker:
    def test_starts_closed(self):
        cb = CircuitBreaker()
        assert cb.state == "closed"
        assert cb.can_execute() is True

    def test_opens_after_failures(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"
        assert cb.can_execute() is False

    def test_resets_on_success(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.state == "closed"
        assert cb.can_execute() is True


class TestRetryWithBackoff:
    def test_succeeds_first_try(self):
        @retry_with_backoff(max_retries=3)
        def succeed():
            return "ok"
        assert succeed() == "ok"

    def test_retries_on_failure(self):
        attempts = [0]
        @retry_with_backoff(max_retries=3, base_delay=0.01)
        def fail_then_succeed():
            attempts[0] += 1
            if attempts[0] < 3:
                raise ValueError("fail")
            return "ok"
        assert fail_then_succeed() == "ok"
        assert attempts[0] == 3

    def test_raises_after_max_retries(self):
        @retry_with_backoff(max_retries=2, base_delay=0.01)
        def always_fail():
            raise ValueError("always")
        with pytest.raises(ValueError):
            always_fail()


class TestSafeExecute:
    def test_returns_result(self):
        assert safe_execute(lambda: 42) == 42

    def test_returns_fallback_on_error(self):
        def fail():
            raise ValueError("no")
        assert safe_execute(fail, fallback="fallback") == "fallback"


class TestErrorHandler:
    def test_handle_tool_error_auth(self):
        result = error_handler.handle_tool_error("test", "401 Unauthorized")
        assert "Authentication" in result or "API key" in result

    def test_handle_tool_error_rate_limit(self):
        result = error_handler.handle_tool_error("test", "429 Too Many")
        assert "Rate" in result or "Wait" in result
