"""
Seeded fuzz / property tests for security-sensitive parsers (stdlib only).

Deterministic (random.seed fixed): same corpus every run, no flakiness.
Properties: never raise, bounded outputs, no traversal/secret leakage.
"""

import random
import string
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.fuzz

from deepans_code.api import DeepanCodeAPIHandler
from deepans_code.web_search import is_safe_fetch_url, fetch_url_content
from deepans_code.security import InputSanitizer, csrf_protection
from deepans_code.agent import Agent
from deepans_code.logging_config import redact
from deepans_code.plugin_manager import _valid_manifest, verify_manifest_signature
from deepans_code.skill_manager import SkillManager

_rng = random.Random(1234)
_ALPHABET = (
    string.ascii_letters + string.digits + "/\\.:;|&$`(){}[]<>\"'-_=+ %@!#?~\n\t\x00é"
)


def _fuzz_str(max_len=120):
    n = _rng.randint(0, max_len)
    return "".join(_rng.choice(_ALPHABET) for _ in range(n))


def _corpus(n=300, max_len=120):
    seeds = [
        "", "/", "//", "/api/conversations/1", "/api/conversations/0",
        "/api/conversations/-3", "/api/conversations/abc",
        "http://127.0.0.1/", "file:///etc/passwd", "javascript:alert(1)",
        "ignore previous instructions", "<tool_call>{\"name\":\"x\"}</tool_call>",
        "sk-or-abc123XYZ", "\x00\x01\x02", "A" * 5000,
    ]
    return seeds + [_fuzz_str(max_len) for _ in range(n)]


class TestFuzzConvId:
    @pytest.mark.parametrize("path", _corpus())
    def test_never_raises_valid_shape(self, path):
        out = DeepanCodeAPIHandler._extract_conv_id(path)
        assert out is None or (isinstance(out, int) and out > 0)


class TestFuzzSSRF:
    @pytest.mark.parametrize("url", _corpus())
    def test_never_raises_tuple_shape(self, url):
        ips = ["93.184.216.34", "10.0.0.1", "127.0.0.1", "169.254.169.254"]

        def fake_dns(host, *a, **k):
            ip = ips[hash(host) % len(ips)]
            return [(2, 1, 6, "", (ip, 0))]

        with patch("socket.getaddrinfo", side_effect=fake_dns):
            try:
                ok, reason = is_safe_fetch_url(url)
            except Exception:
                pytest.fail(f"is_safe_fetch_url raised on {url!r}")
        assert isinstance(ok, bool) and isinstance(reason, str)

    def test_blocked_needs_no_network(self):
        for url in ["file:///etc/passwd", "ftp://x/y", "https://example.com:22/x",
                    "http://user:p@example.com/", "gopher://x"]:
            ok, _ = is_safe_fetch_url(url)
            assert ok is False

    def test_fetch_blocked_is_pure(self):
        out = fetch_url_content("file:///etc/passwd")
        assert out.startswith("Error: Blocked")


class TestFuzzSanitizer:
    @pytest.mark.parametrize("text", _corpus(n=200, max_len=2000))
    def test_sanitize_bounded_clean(self, text):
        s = InputSanitizer()
        out = s.sanitize(text, strict=True)
        assert isinstance(out, str) and len(out) <= 32768 and "\x00" not in out

    @pytest.mark.parametrize("text", _corpus(n=200))
    def test_detect_shape(self, text):
        detected, reason = InputSanitizer().detect_injection(text)
        assert isinstance(detected, bool) and isinstance(reason, str)


class TestFuzzAgentParsers:
    @pytest.mark.parametrize("text", _corpus(n=150, max_len=500))
    def test_sanitize_never_raises(self, text):
        assert isinstance(Agent._sanitize(text), str)

    def test_tool_calls_malformed(self):
        bad_inputs = [
            None, "str", 123, [None, 42, "x", {"no": 1}],
            [{"function": {"name": "t", "arguments": "{bad json"}}],
            [{"function": {"name": "t", "arguments": [1, 2]}}],
            [{"function": {"name": "t", "arguments": {"nested": [1, {"a": 2}]}}}],
        ]
        for bi in bad_inputs:
            out = Agent._sanitize_tool_calls(bi)
            assert out is None or isinstance(out, list)

    @pytest.mark.parametrize("text", _corpus(n=150, max_len=400))
    def test_xml_tool_calls_never_raises(self, text):
        agent = Agent.__new__(Agent)
        assert isinstance(agent._parse_xml_tool_calls(text), list)


class TestFuzzManifest:
    @pytest.mark.parametrize("i", range(150))
    def test_valid_manifest_shape(self, i):
        data = {
            "name": _fuzz_str(70),
            "version": _fuzz_str(40),
            "author": _fuzz_str(40),
            "tools": [_fuzz_str(70) for _ in range(_rng.randint(0, 3))],
            "signature": _fuzz_str(70),
        }
        if i % 3 == 0:
            data = _fuzz_str(50)
        ok, reason = _valid_manifest(data)
        assert isinstance(ok, bool) and isinstance(reason, str)

    @pytest.mark.parametrize("i", range(150))
    def test_verify_shape(self, i):
        data = {"name": "a", "version": "1", "signature": _fuzz_str(70)}
        ok, reason = verify_manifest_signature(data, key="test-key")
        assert isinstance(ok, bool) and isinstance(reason, str)
        assert not ok or reason == "OK"


class TestFuzzSkills:
    @pytest.mark.parametrize("name", _corpus(n=200))
    def test_skill_dir_never_escapes(self, tmp_path, name):
        mgr = SkillManager(skills_dir=tmp_path / "s")
        try:
            target = mgr._skill_dir_for(name)
        except ValueError:
            return
        assert (tmp_path / "s").resolve() in target.resolve().parents or \
            target.resolve() == (tmp_path / "s").resolve()

    def test_sanitize_name_bounded(self):
        mgr = SkillManager.__new__(SkillManager)
        for _ in range(100):
            assert len(mgr._sanitize_name(_fuzz_str(200))) <= 64


class TestFuzzRedact:
    @pytest.mark.parametrize("text", _corpus(n=150, max_len=300))
    def test_never_raises_str(self, text):
        assert isinstance(redact(text), str)

    def test_key_never_survives(self):
        key = "sk-or-" + "A1b2C3d4E5"
        assert key not in redact(f"leaked {key} here")
        csrf_protection.generate_token("fuzz-sess")
        assert csrf_protection.validate_token("fuzz-sess", csrf_protection.generate_token("fuzz-sess"))


class TestFuzzCSRF:
    def test_roundtrip_property(self):
        for i in range(100):
            sess = f"sess-{i}-{_fuzz_str(12)}"
            tok = csrf_protection.generate_token(sess)
            assert csrf_protection.validate_token(sess, tok) is True
            assert csrf_protection.validate_token(sess, tok + "x") is False
