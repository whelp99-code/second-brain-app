"""Model citations must refer to the bounded input actually sent to the model."""

from __future__ import annotations

import json

import pytest

from sb.life_contracts import LifeInputError
from sb.life_model_policy import generate_after_reservation, reserve
from sb.store.ledger import Ledger
from sb.store.life_journal import LifeJournal
from tests.test_life_workflow_objects import NOW, SCOPES, SOURCES, seed


@pytest.mark.parametrize("index, rejected", [(0, False), (39, False), (40, True)])
def test_model_cannot_cite_omitted_records(tmp_path, index, rejected):
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
            def generate(self, prompt):
                assert events[0].event_id in prompt
                assert events[39].event_id in prompt
                assert events[40].event_id not in prompt
                return json.dumps({"items": [{"text": "합성 요약", "event_ids": [selected_id]}]})

        def execute():
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
                execute()
        else:
            assert selected_id in execute()
