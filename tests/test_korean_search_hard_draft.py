"""Hard-case Korean eval draft is loadable and does not replace the user set."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Final, cast

from scripts.korean_search_evaluation import load_dataset, object_value

FIXTURE: Final = Path(__file__).parent / "fixtures/korean_search_hard_v1.json"
REQUIRED_KINDS: Final = frozenset({
    "stale_decision",
    "no_answer",
    "mixed_alnum",
    "short_token",
    "spacing",
    "multi_gold",
    "natural_question",
    "paraphrase",
})


def test_hard_draft_is_synthetic_and_covers_missing_kinds() -> None:
    dataset = load_dataset(object_value(cast(object, json.loads(FIXTURE.read_text()))))
    assert dataset.origin == "synthetic"
    assert dataset.id == "korean-hard-draft-v1"
    assert REQUIRED_KINDS <= {case.kind for case in dataset.cases}
    assert any(case.forbidden for case in dataset.cases)
    assert any(case.kind == "no_answer" for case in dataset.cases)
    assert any(len(case.expected) > 1 for case in dataset.cases)
