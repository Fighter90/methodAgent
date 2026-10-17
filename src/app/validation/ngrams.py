"""Проверка оригинальности по 8-граммам (V-17) и сходство тем (V-25)."""

from __future__ import annotations

import re
from difflib import SequenceMatcher


def _tokens(text: str) -> list[str]:
    return re.findall(r'[a-zа-яё0-9]+', text.lower())


def ngrams(tokens: list[str], n: int = 8) -> set[tuple[str, ...]]:
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def overlap_share(text: str, reference: str, n: int = 8) -> float:
    """Доля 8-грамм текста, которые встречаются в референсе."""
    grams = ngrams(_tokens(text), n)
    if not grams:
        return 0.0
    ref = ngrams(_tokens(reference), n)
    return len(grams & ref) / len(grams)


def similarity(a: str, b: str) -> float:
    """Сходство названий тем; эмбеддинги bge-m3 подключаются в kb, здесь — дешёвый резерв."""
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()
