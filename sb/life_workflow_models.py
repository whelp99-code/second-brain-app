"""Locked reservation and settlement commands for Life model calls."""

from __future__ import annotations

from collections.abc import Mapping

from sb.config import Config
from sb.effect_values import JsonInput
from sb.life_config import settings
from sb.life_contracts import LifeInputError
from sb.life_fields import boolean, integer, string
from sb.life_journal_contracts import JournalRow
from sb.life_values import text
from sb.life_workflow_contracts import WorkflowContext
from sb.store.life_journal import LifeJournal


def perform_model(
    config: Config,
    journal: LifeJournal,
    command: str,
    data: Mapping[str, JsonInput],
    common: WorkflowContext,
) -> JournalRow:
    opts = settings(config)
    events, scopes, source_ids, now = (
        common["events"],
        common["scopes"],
        common["source_ids"],
        common["now"],
    )
    if command == "model_reserve":
        from sb.life_model_policy import reserve

        if set(data) - {
            "event_ids",
            "idempotency_key",
            "external",
            "estimated_tokens",
            "maximum_cost_micros",
        }:
            raise LifeInputError("LIFE_UNKNOWN_FIELD")
        ids = data.get("event_ids")
        if (
            not isinstance(ids, list)
            or not ids
            or len(ids) > 40
            or any(not isinstance(i, str) for i in ids)
        ):
            raise LifeInputError("LIFE_MODEL_INPUT_INVALID")
        selected = tuple(e for e in events if e.event_id in ids)
        if len(selected) != len(set(ids)):
            raise LifeInputError("LIFE_EVENT_NOT_FOUND")
        budget = config.raw.get("life_model_budget", {})
        if not isinstance(budget, Mapping) or set(budget) - {"daily_tokens", "daily_cost_micros"}:
            raise LifeInputError("LIFE_MODEL_BUDGET_INVALID")
        return reserve(
            journal,
            key=text(data.get("idempotency_key"), maximum=256),
            events=selected,
            scopes=scopes,
            source_ids=source_ids,
            now=now,
            external=boolean(data.get("external", False), "LIFE_MODEL_POLICY_INVALID"),
            daily_calls=opts.daily_model_calls,
            estimated_tokens=integer(
                data.get("estimated_tokens", 4096), "LIFE_MODEL_BUDGET_INVALID"
            ),
            maximum_cost_micros=integer(
                data.get("maximum_cost_micros", 0), "LIFE_MODEL_BUDGET_INVALID"
            ),
            timezone=opts.timezone,
            daily_tokens=integer(budget.get("daily_tokens", 100000), "LIFE_MODEL_BUDGET_INVALID"),
            daily_cost_micros=integer(
                budget.get("daily_cost_micros", 1000000), "LIFE_MODEL_BUDGET_INVALID"
            ),
        )
    if command == "model_settle":
        from sb.life_model_policy import settle

        if set(data) - {"reservation_id", "state", "actual_tokens", "actual_cost_micros"}:
            raise LifeInputError("LIFE_UNKNOWN_FIELD")
        return settle(
            journal,
            text(data.get("reservation_id"), maximum=180),
            state=string(data.get("state"), "LIFE_MODEL_RESULT_INVALID"),
            actual_tokens=integer(data.get("actual_tokens", 0), "LIFE_MODEL_RESULT_INVALID"),
            actual_cost_micros=integer(
                data.get("actual_cost_micros", 0), "LIFE_MODEL_RESULT_INVALID"
            ),
            **common,
        )
    raise LifeInputError("LIFE_ROUTE_NOT_FOUND")
