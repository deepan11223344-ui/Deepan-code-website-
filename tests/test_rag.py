"""Tests for TF-IDF vector RAG store (tmp-isolated, no home writes)."""

import pytest
from deepans_code.rag import SimpleVectorStore, tokenize

CODE_DOC = "python socket server threading accept client connection bind listen"
RECIPE_DOC = "chocolate cake recipe baking flour sugar oven delicious dessert"


@pytest.fixture
def store(tmp_path):
    return SimpleVectorStore(persist_dir=tmp_path / "rag")


def _seeded(tmp_path):
    s = SimpleVectorStore(persist_dir=tmp_path / "rag")
    s.add_document(CODE_DOC, {"source": "server.py"})
    s.add_document(RECIPE_DOC, {"source": "cake.md"})
    return s


class TestVectorSearch:
    def test_relevant_doc_ranks_first(self, tmp_path):
        s = _seeded(tmp_path)
        # Only the code doc shares tokens → single hit.
        exact = s.search("python socket server", top_k=2)
        assert len(exact) == 1
        assert exact[0]["metadata"]["source"] == "server.py"
        # Query overlapping both docs ranks the 3-term match above the 1-term match.
        results = s.search("python server delicious", top_k=2)
        assert len(results) == 2
        assert results[0]["metadata"]["source"] == "server.py"
        assert results[0]["score"] > results[1]["score"]

    def test_scores_are_cosine_bounded(self, tmp_path):
        s = _seeded(tmp_path)
        for r in s.search("python delicious", top_k=2):
            assert 0.0 < r["score"] <= 1.0

    def test_empty_and_unknown_query(self, store):
        store.add_document(CODE_DOC)
        assert store.search("") == []
        assert store.search("zzzqqq xxyyww") == []

    def test_empty_store(self, store):
        assert store.search("python") == []

    def test_incremental_indexing(self, tmp_path):
        s = _seeded(tmp_path)
        before = s.search("rust borrow checker", top_k=5)
        assert all(r["metadata"]["source"] != "rust.md" for r in before)
        s.add_document("rust borrow checker ownership lifetimes systems programming")
        after = s.search("rust borrow checker", top_k=1)
        assert after[0]["score"] > 0

    def test_persist_and_reload(self, tmp_path):
        s = _seeded(tmp_path)
        s._save()
        s2 = SimpleVectorStore(persist_dir=tmp_path / "rag")
        r1 = s.search("python socket", top_k=2)
        r2 = s2.search("python socket", top_k=2)
        assert [r["metadata"]["source"] for r in r1] == [r["metadata"]["source"] for r in r2]

    def test_add_codebase(self, tmp_path):
        src = tmp_path / "proj"
        src.mkdir()
        (src / "a.py").write_text("def hello():\n    return 'world'\n", encoding="utf-8")
        (src / "b.py").write_text("import socket\ns = socket.socket()\n", encoding="utf-8")
        (src / "notes.txt").write_text("ignore me", encoding="utf-8")
        s = SimpleVectorStore(persist_dir=tmp_path / "rag")
        assert s.add_codebase(str(src)) == 2
        assert s.search("socket", top_k=1)[0]["metadata"]["source"] == "b.py"

    def test_get_context_bounded(self, tmp_path):
        s = _seeded(tmp_path)
        ctx = s.get_context("python server", max_tokens=100)
        assert "socket" in ctx
        assert len(ctx) <= 100 * 4 + len("\n---\n")
        # A budget smaller than the first hit yields nothing rather than overflow.
        assert s.get_context("python server", max_tokens=1) == ""

    def test_tokenizer(self):
        assert "hello" in tokenize("Hello, WORLD!")
        assert tokenize("a ab") == []
