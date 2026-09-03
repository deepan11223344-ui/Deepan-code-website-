"""Tests for database module."""

import os
import json
import pytest
import tempfile
from pathlib import Path
from deepans_code.database import Database


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db = Database(db_path=Path(db_path))
    yield db
    os.unlink(db_path)


class TestDatabase:
    def test_create_conversation(self, temp_db):
        conv_id = temp_db.create_conversation(title="Test Conv", model="openrouter/free")
        assert conv_id > 0

    def test_save_and_get_messages(self, temp_db):
        conv_id = temp_db.create_conversation()
        temp_db.save_message(conv_id, "user", "Hello")
        temp_db.save_message(conv_id, "assistant", "Hi there!")
        messages = temp_db.get_messages(conv_id)
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hello"
        assert messages[1]["role"] == "assistant"

    def test_get_conversations(self, temp_db):
        temp_db.create_conversation(title="Conv 1")
        temp_db.create_conversation(title="Conv 2")
        convs = temp_db.get_conversations()
        assert len(convs) == 2

    def test_delete_conversation(self, temp_db):
        conv_id = temp_db.create_conversation()
        temp_db.save_message(conv_id, "user", "test")
        temp_db.delete_conversation(conv_id)
        conv = temp_db.get_conversation(conv_id)
        assert conv is None

    def test_export_markdown(self, temp_db):
        conv_id = temp_db.create_conversation(title="Export Test")
        temp_db.save_message(conv_id, "user", "Hello")
        temp_db.save_message(conv_id, "assistant", "Hi!")
        md = temp_db.export_conversation(conv_id, fmt="markdown")
        assert "Export Test" in md
        assert "Hello" in md

    def test_export_json(self, temp_db):
        conv_id = temp_db.create_conversation()
        temp_db.save_message(conv_id, "user", "test")
        js = temp_db.export_conversation(conv_id, fmt="json")
        data = json.loads(js)
        assert "conversation" in data
        assert "messages" in data

    def test_search_messages(self, temp_db):
        conv_id = temp_db.create_conversation()
        temp_db.save_message(conv_id, "user", "python is great")
        temp_db.save_message(conv_id, "user", "java is okay")
        results = temp_db.search_messages("python")
        assert len(results) == 1
        assert "python" in results[0]["content"]

    def test_stats(self, temp_db):
        conv_id = temp_db.create_conversation()
        temp_db.save_message(conv_id, "user", "hello")
        stats = temp_db.get_stats()
        assert stats["conversations"] == 1
        assert stats["messages"] == 1

    def test_tool_calls_json(self, temp_db):
        conv_id = temp_db.create_conversation()
        tool_calls = [{"id": "call_1", "function": {"name": "read_file", "arguments": "{}"}}]
        temp_db.save_message(conv_id, "assistant", "", tool_calls=tool_calls)
        messages = temp_db.get_messages(conv_id)
        assert messages[0]["tool_calls"] == tool_calls
