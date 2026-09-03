"""Tests for tools module."""

import os
import tempfile
import pytest
from pathlib import Path
from deepans_code.tools import (
    _read_file, _create_file, _edit_file, _list_dir, _delete_file,
    _run_command, set_workspace
)


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        set_workspace(tmpdir)
        yield tmpdir


class TestReadFile:
    def test_read_existing_file(self, temp_workspace):
        p = Path(temp_workspace) / "test.txt"
        p.write_text("hello world")
        result = _read_file(str(p))
        assert result == "hello world"

    def test_read_nonexistent_file(self, temp_workspace):
        result = _read_file(str(Path(temp_workspace) / "missing.txt"))
        assert "Error" in result

    def test_read_outside_workspace(self, temp_workspace):
        result = _read_file("/etc/passwd")
        assert "Error" in result


class TestCreateFile:
    def test_create_file(self, temp_workspace):
        p = Path(temp_workspace) / "new.txt"
        result = _create_file(str(p), "new content")
        assert "Successfully" in result
        assert p.read_text() == "new content"

    def test_create_in_subdirectory(self, temp_workspace):
        p = Path(temp_workspace) / "sub" / "dir" / "file.txt"
        result = _create_file(str(p), "nested")
        assert "Successfully" in result

    def test_create_outside_workspace(self, temp_workspace):
        result = _create_file("/tmp/evil.txt", "bad")
        assert "Error" in result


class TestEditFile:
    def test_edit_file(self, temp_workspace):
        p = Path(temp_workspace) / "edit.txt"
        p.write_text("hello world")
        result = _edit_file(str(p), "hello", "goodbye")
        assert "Successfully" in result
        assert p.read_text() == "goodbye world"

    def test_edit_nonexistent_text(self, temp_workspace):
        p = Path(temp_workspace) / "edit2.txt"
        p.write_text("hello world")
        result = _edit_file(str(p), "notfound", "new")
        assert "Error" in result or "not found" in result.lower()


class TestListDir:
    def test_list_dir(self, temp_workspace):
        (Path(temp_workspace) / "a.txt").write_text("a")
        (Path(temp_workspace) / "b.txt").write_text("b")
        result = _list_dir(temp_workspace)
        assert "a.txt" in result
        assert "b.txt" in result

    def test_list_nonexistent_dir(self, temp_workspace):
        result = _list_dir(str(Path(temp_workspace) / "missing"))
        assert "Error" in result


class TestDeleteFile:
    def test_delete_file(self, temp_workspace):
        p = Path(temp_workspace) / "del.txt"
        p.write_text("delete me")
        result = _delete_file(str(p))
        assert "Successfully" in result
        assert not p.exists()

    def test_delete_nonexistent(self, temp_workspace):
        result = _delete_file(str(Path(temp_workspace) / "missing.txt"))
        assert "Error" in result


class TestRunCommand:
    def test_safe_command(self, temp_workspace):
        result = _run_command("echo hello")
        assert "hello" in result

    def test_blocked_command(self, temp_workspace):
        result = _run_command("rm -rf /")
        assert "Error" in result or "blocked" in result.lower()
