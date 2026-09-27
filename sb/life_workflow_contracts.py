"""Typed arguments and results for locked Life workflow dispatch."""

from datetime import datetime

from typing_extensions import TypedDict

from sb.life_contracts import LifeEventV1
from sb.life_journal_contracts import JournalRow


class WorkflowContext(TypedDict):
    events: tuple[LifeEventV1, ...]
    scopes: tuple[str, ...]
    source_ids: tuple[str, ...]
    now: datetime


class QuestionsResult(TypedDict, closed=True):
    questions: list[JournalRow]


class QuestionResult(TypedDict, closed=True):
    question: JournalRow


class BriefingsResult(TypedDict, closed=True):
    briefings: list[JournalRow]
    notifications_sent: bool


type WorkflowResult = JournalRow | QuestionsResult | QuestionResult | BriefingsResult
