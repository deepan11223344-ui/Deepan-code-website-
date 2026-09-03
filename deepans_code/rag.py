"""
RAG (Retrieval-Augmented Generation) module for DeepanCode.
TF-IDF vector store for code context and knowledge retrieval.

Each document is a sparse TF-IDF vector over the corpus vocabulary; ranking
is cosine similarity between query and document vectors. Pure standard
library (no FAISS/scipy), incremental indexing, atomic persistence.
"""

import json
import logging
import math
import os
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger("deepans_code.rag")

RAG_DIR = Path.home() / ".deepans-code" / "rag"
INDEX_FILE = RAG_DIR / "index.json"  # legacy alias; instances use self._index_file

_TOKEN_RE = re.compile(r"[a-z0-9]+")
MAX_DOCS = 1000
MAX_DOC_CHARS = 20000


def tokenize(text: str) -> List[str]:
    """Lowercase alphanumeric tokens (code-friendly: splits snake_case,
    camelCase boundaries fall out via the digit/letter runs)."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if len(t) > 2]


class SimpleVectorStore:
    """TF-IDF vector store with cosine-similarity ranking."""

    def __init__(self, persist_dir: Optional[Path] = None):
        self.documents: List[Dict] = []
        # Parallel arrays (rebuilt by _build_index, updated by _index_document):
        self._term_freqs: List[Counter] = []   # per-doc token counts
        self._doc_freq: Counter = Counter()    # token -> #docs containing it
        self._persist_dir = Path(persist_dir) if persist_dir else RAG_DIR
        self._index_file = self._persist_dir / "index.json"
        self._load()

    # -- persistence ----------------------------------------------------
    def _load(self):
        if self._index_file.exists():
            try:
                with open(self._index_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    docs = data.get("documents", [])
                    if isinstance(docs, list):
                        self.documents = docs[-MAX_DOCS:]
                        self._build_index()
            except Exception:
                self.documents = []

    def _save(self):
        try:
            self._persist_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"RAG persist dir unavailable: {e}")
            return
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(self._persist_dir), prefix="index.", suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump({"documents": self.documents[-MAX_DOCS:]}, f,
                          ensure_ascii=False, default=str)
            os.replace(tmp_path, self._index_file)
        except (TypeError, ValueError, OSError) as e:
            logger.error(f"RAG persist failed, keeping in-memory index: {e}")
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass

    # -- indexing -------------------------------------------------------
    def add_document(self, text: str, metadata: Dict = None):
        if not isinstance(text, str) or not text or len(text) < 10:
            return
        if not isinstance(metadata, dict):
            metadata = {}
        text = text[:MAX_DOC_CHARS]
        doc = {"text": text, "metadata": metadata or {}, "id": len(self.documents)}
        self.documents.append(doc)
        if len(self.documents) > MAX_DOCS:
            # Evict oldest and rebuild (keeps ids/positions consistent).
            self.documents = self.documents[-MAX_DOCS:]
            for i, d in enumerate(self.documents):
                d["id"] = i
            self._build_index()
        else:
            self._index_document(len(self.documents) - 1, text)
        if len(self.documents) % 100 == 0:
            self._save()

    def _index_document(self, doc_id: int, text: str):
        counts = Counter(tokenize(text))
        while len(self._term_freqs) <= doc_id:
            self._term_freqs.append(Counter())
        self._term_freqs[doc_id] = counts
        for token in counts:
            self._doc_freq[token] += 1

    def _build_index(self):
        self._term_freqs = []
        self._doc_freq = Counter()
        for i, doc in enumerate(self.documents):
            self._index_document(i, doc["text"])

    # -- retrieval ------------------------------------------------------
    def _idf(self, token: str) -> float:
        # Smoothed IDF: always > 0, no division by zero.
        return math.log((1 + len(self.documents)) / (1 + self._doc_freq.get(token, 0))) + 1.0

    def search(self, query: str, top_k: int = 5) -> List[Dict]:
        try:
            top_k = int(top_k)
        except (ValueError, TypeError):
            top_k = 5
        if top_k <= 0:
            return []
        query_counts = Counter(tokenize(query or ""))
        if not query_counts or not self.documents:
            return []
        # Query TF-IDF vector + norm.
        q_weights = {t: c * self._idf(t) for t, c in query_counts.items()}
        q_norm = math.sqrt(sum(w * w for w in q_weights.values()))
        if q_norm == 0:
            return []
        scored = []
        for doc_id, doc in enumerate(self.documents):
            tf = self._term_freqs[doc_id] if doc_id < len(self._term_freqs) else Counter()
            dot = 0.0
            d_norm_sq = 0.0
            for token, count in tf.items():
                w = count * self._idf(token)
                d_norm_sq += w * w
                if token in q_weights:
                    dot += w * q_weights[token]
            if dot == 0 or d_norm_sq == 0:
                continue
            scored.append((dot / (math.sqrt(d_norm_sq) * q_norm), doc_id))
        scored.sort(key=lambda s: s[0], reverse=True)
        return [{
            "text": self.documents[doc_id]["text"][:500],
            "metadata": self.documents[doc_id]["metadata"],
            "score": round(score, 6),
        } for score, doc_id in scored[:max(1, top_k)]]

    def add_codebase(self, directory: str, extensions: List[str] = None, max_files: int = 500):
        if extensions is None:
            extensions = [".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java"]
        dir_path = Path(directory)
        if not dir_path.exists():
            return 0
        count = 0
        try:
            entries = list(dir_path.rglob("*"))
        except OSError as e:
            logger.error(f"RAG codebase scan failed: {e}")
            return 0
        for file_path in entries:
            if count >= max_files:
                break
            if file_path.is_file() and file_path.suffix in extensions:
                try:
                    if file_path.stat().st_size > 200_000:
                        continue  # skip huge files
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    if len(content) > 10:
                        rel_path = str(file_path.relative_to(dir_path))
                        self.add_document(content, {"source": rel_path, "type": "code"})
                        count += 1
                except Exception:
                    continue
        self._save()
        return count

    def get_context(self, query: str, max_tokens: int = 2000) -> str:
        results = self.search(query, top_k=3)
        if not results:
            return ""
        context_parts = []
        total_chars = 0
        budget_chars = max_tokens * 4  # ~4 chars per token
        for r in results:
            text = r["text"]
            if total_chars + len(text) > budget_chars:
                break
            context_parts.append(text)
            total_chars += len(text)
        return "\n---\n".join(context_parts)


rag_store = SimpleVectorStore()
