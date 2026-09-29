"""Model citations must refer to the bounded input actually sent to the model."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sb.effect_values import JsonValue
from sb.life_contracts import LifeInputError
from sb.life_model_policy import generate_after_reservation, reserve
from sb.store.ledger import Ledger
from sb.store.life_journal import LifeJournal
from tests.test_life_contracts import NOW, payload, policy
from tests.test_life_workflow_objects import SCOPES, SOURCES, seed


@pytest.mark.parametrize("index, rejected", [(0, False), (39, False), (40, True)])
def test_model_cannot_cite_omitted_records(tmp_path: Path, index: int, rejected: bool) -> None:
    with Ledger(tmp_path) as ledger:
        events = seed(ledger.life_store(), 41)
        reservation = reserve(
            LifeJournal(ledger.life_store()),
            key="bounded-input",
            events=events,
            external=False,
            scopes=SCOPES,
            source_ids=SOURCES,
            now=NOW,
            daily_calls=1,
        )
        selected_id = events[index].event_id

        class Model:
            def generate(self, prompt: str, **kwargs: JsonValue) -> str:
                assert prompt and not kwargs
                assert events[0].event_id in prompt
                assert events[39].event_id in prompt
                assert events[40].event_id not in prompt
                return json.dumps({"items": [{"text": "합성 요약", "event_ids": [selected_id]}]})

        def execute() -> str:
            return generate_after_reservation(
                reservation,
                Model(),
                events=events,
                external=False,
                scopes=SCOPES,
                source_ids=SOURCES,
            )

        if rejected:
            with pytest.raises(LifeInputError, match="LIFE_MODEL_OUTPUT_INVALID"):
                _ = execute()
        else:
            assert selected_id in execute()


def test_model_cannot_cite_out_of_scope_event(tmp_path):
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        events = seed(store)
        hidden = store.accept(
            payload(source_item_id="foreign", body="FORBIDDEN_FOREIGN_BODY"),
            policy(source_id="private", scopes=("owner:foreign",)),
            key="foreign", now=NOW,
        )
        reservation = reserve(
            LifeJournal(store), key="scope-boundary", events=events, external=False,
            scopes=SCOPES, source_ids=SOURCES, now=NOW, daily_calls=1,
        )
        prompts = []

        class Model:
            def generate(self, prompt):
                prompts.append(prompt)
                return json.dumps({"items": [{
                    "text": "fixture", "event_ids": [events[0].event_id, hidden.event_id],
                }]})

        with pytest.raises(LifeInputError, match="LIFE_MODEL_OUTPUT_INVALID"):
            generate_after_reservation(
                reservation, Model(), events=events, external=False,
                scopes=SCOPES, source_ids=SOURCES,
            )
        assert len(prompts) == 1
        sent = json.loads(prompts[0].split("\n", 1)[1])
        assert [row["event_id"] for row in sent] == [events[0].event_id]
        assert "FORBIDDEN_FOREIGN_BODY" not in prompts[0]
