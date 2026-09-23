"""Minimal keyword retriever. Swap for Azure AI Search / pgvector / Qdrant in production."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "can", "do", "does", "for", "from", "how", "i",
    "if", "in", "into", "is", "it", "keeps", "me", "my", "of", "on", "or", "please", "the", "to",
    "what", "when", "where", "which", "who", "why", "with", "you", "your", "redacted", "email",
}


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS and len(t) > 1]


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    content: str
    tags: tuple[str, ...] = ()


class KeywordRetriever:
    def __init__(self, documents: list[Document]) -> None:
        self.documents = documents
        self._index = [
            (doc, set(tokenize(doc.content)), set(tokenize(doc.title + " " + " ".join(doc.tags))))
            for doc in documents
        ]

    @classmethod
    def from_json(cls, path: str | Path) -> KeywordRetriever:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls([Document(d["id"], d["title"], d["content"], tuple(d.get("tags", []))) for d in raw])

    def search(self, query: str, top_k: int = 3) -> list[tuple[Document, float]]:
        q = set(tokenize(query))
        if not q:
            return []
        scored = []
        for doc, body, header in self._index:
            score = len(q & body) + 2.0 * len(q & header)  # title/tag matches weigh more
            if score > 0:
                scored.append((doc, round(score / len(q), 3)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]
