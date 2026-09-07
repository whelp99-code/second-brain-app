"""Exact ranking compatibility and bounded work for repeated-token corpora."""
from __future__ import annotations

import random
from collections.abc import Sequence

import pytest

from sb import conflict_lexical
from sb.conflict_lexical import LexicalMatch, lexical_top
from sb.contracts import PageSpec, Unit
from tests.fixtures.conflict_lexical_reference import reference


def unit(identity: str, text: str) -> Unit:
    return Unit(identity, "a" * 64, "0-100", text, f"fixture:{identity}")


@pytest.mark.parametrize("seed", range(20))
def test_rankings_match_independent_reference_for_mixed_and_duplicate_ids(seed: int) -> None:
    generator = random.Random(seed)
    vocabulary = ("기억", "정정", "a", "a", "a", "memory", "MEMORY", "한글", "한글", "42", "")
    for _ in range(20):
        def text() -> str:
            return " / ".join(generator.choices(vocabulary, k=generator.randrange(12)))

        units = [unit(f"u{generator.randrange(18):02d}", text()) for _ in range(generator.randrange(28))]
        pages = [PageSpec(generator.choice((f"page-{i}", f"u{generator.randrange(18):02d}")),
                          "Page", text(), [], "active") for i in range(generator.randrange(8))]
        assert lexical_top(units, pages) == reference(units, pages)


def test_common_tokens_share_ranking_work_and_return_exact_global_top(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    # Instrument internal work here; the public result is checked independently.
    real = conflict_lexical._Candidates._score  # pyright: ignore[reportPrivateUsage]

    def counted(self: conflict_lexical._Candidates, signature: tuple[tuple[str, int], ...]) -> tuple[tuple[str, int], ...]:  # pyright: ignore[reportPrivateUsage]
        nonlocal calls
        calls += 1
        return real(self, signature)

    monkeypatch.setattr(conflict_lexical._Candidates, "_score", counted)  # pyright: ignore[reportPrivateUsage]
    units = [unit(f"u{i:05d}", f"고유단어{i} " + "공통 " * 80) for i in range(10000)]
    assert lexical_top(units, ()) == tuple(LexicalMatch("u00000", f"u{i:05d}", 80.0) for i in range(1, 11))
    assert calls == 1


@pytest.mark.parametrize("texts", ((), ("",), ("one", "two"), ("a a", "a", "a a a")))
def test_small_edge_cases(texts: Sequence[str]) -> None:
    units = [unit(str(i), text) for i, text in enumerate(texts)]
    assert lexical_top(units, ()) == reference(units, ())


def test_tokenization_matches_previous_unicode_character_rules() -> None:
    # Exhaustively compare character categories while retaining normalization.
    from sb.conflict_lexical import _tokens  # pyright: ignore[reportPrivateUsage]
    from tests.fixtures.conflict_lexical_reference import tokens

    all_characters = ''.join(chr(value) for value in range(0x110000))
    assert _tokens(all_characters) == tokens(all_characters)
    assert _tokens('한글_한글 İ ß ① 𐐀 🧠') == tokens('한글_한글 İ ß ① 𐐀 🧠')
