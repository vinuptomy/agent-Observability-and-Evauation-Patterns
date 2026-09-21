"""Lexical helpers used by deterministic metrics and the offline MockJudge."""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from typing import Any

_WORD = re.compile(r"[a-z0-9äöüß]+", re.I)
STOPWORDS = frozenset(
    "a an the and or of to in on for with by at from is are was were be been it this that these those "
    "your you our we i my me as has have had can could will would should may might not no do does did "
    "so if then than there their them they he she his her its into about after before".split()
)


def tokenize(text: Any, drop_stopwords: bool = True) -> list[str]:
    toks = [t.lower() for t in _WORD.findall(str(text or ""))]
    return [t for t in toks if t not in STOPWORDS] if drop_stopwords else toks


def token_recall(reference: Any, candidate: Any) -> float:
    ref, cand = tokenize(reference), set(tokenize(candidate))
    if not ref:
        return 1.0
    return sum(1 for t in ref if t in cand) / len(ref)


def token_precision(candidate: Any, reference: Any) -> float:
    cand, ref = tokenize(candidate), set(tokenize(reference))
    if not cand:
        return 0.0
    return sum(1 for t in cand if t in ref) / len(cand)


def token_f1(reference: Any, candidate: Any) -> float:
    ref, cand = Counter(tokenize(reference)), Counter(tokenize(candidate))
    if not ref and not cand:
        return 1.0
    overlap = sum((ref & cand).values())
    if overlap == 0:
        return 0.0
    p, r = overlap / sum(cand.values()), overlap / sum(ref.values())
    return 2 * p * r / (p + r)


def lcs_length(a: Sequence[Any], b: Sequence[Any]) -> int:
    """Longest common subsequence length (O(n*m), fine for trajectories)."""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b):
            cur.append(prev[j] + 1 if x == y else max(prev[j + 1], cur[j]))
        prev = cur
    return prev[-1]


def f1(precision: float, recall: float) -> float:
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def gini(values: Sequence[float]) -> float:
    vals = sorted(v for v in values if v >= 0)
    n, total = len(vals), sum(vals)
    if n == 0 or total == 0:
        return 0.0
    cum = sum((i + 1) * v for i, v in enumerate(vals))
    return (2 * cum) / (n * total) - (n + 1) / n


def soft_equal(a: Any, b: Any) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().casefold() == b.strip().casefold()
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 1e-9
    return a == b
