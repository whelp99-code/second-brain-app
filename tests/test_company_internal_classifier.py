from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Literal

import pytest

from sb.company_internal_classifier import classify_mail_candidate
from sb.company_memory import MemoryCandidate
from tests.company_classifier_cases import (
    ACTION_VARIANTS,
    ENGLISH_ACTIONS,
    INVALID_EMAILS,
    REPORTED_ACTIONS,
)
from tests.company_internal_auto_support import (
    ACCESS,
    DELETION,
    WORKSPACE,
    calendar_body,
    contact_body,
    progress_body,
)


def candidate_for(body: str) -> MemoryCandidate:
    return MemoryCandidate(
        workspace_id=WORKSPACE,
        candidate_id="classifier:input",
        source_system="mail",
        source_locator="message:input",
        source_event_id="event:input",
        content=body,
        content_digest="sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest(),
        parser_version="mail:1",
        locator={"kind": "message", "ordinal": 1},
        access=ACCESS,
        deletion_sequence=DELETION[0],
        deletion_set_root=DELETION[1],
        state="candidate",
        accepted_at=None,
        rejected_at=None,
        processed_at=None,
    )


@pytest.mark.parametrize(
    ("label", "action"),
    [
        pytest.param(label, action, id=label)
        for label, action in (*REPORTED_ACTIONS, *ACTION_VARIANTS, *ENGLISH_ACTIONS)
    ],
)
def test_unlisted_progress_action_requires_human(label: str, action: str) -> None:
    # Given a correctly structured progress block, not an unparseable payload.
    candidate = candidate_for(progress_body().replace("file the note", action))
    # When the real owner classifier decides whether automation has positive proof.
    classified = classify_mail_candidate(candidate)
    # Then even words absent from veto patterns cannot grant automatic processing.
    assert classified.classification == "human_required", (label, classified)
    assert classified.record_kind is None


@pytest.mark.parametrize("text", [text for _, text in ENGLISH_ACTIONS])
@pytest.mark.parametrize(
    "field", ["name", "name-bare", "email", "phone", "department", "title", "subject"]
)
def test_protected_wording_cannot_move_to_another_record_field(
    text: str,
    field: Literal["name", "name-bare", "email", "phone", "department", "title", "subject"],
) -> None:
    # Given the same protected request moved away from the next-action field.
    match field:
        case "name":
            body = contact_body(name="Ada " + text.title())
        case "name-bare":
            body = contact_body(name=text.title())
        case "email":
            body = contact_body(email=text + "@mail.internal")
        case "phone" | "department":
            body = contact_body() + field + ": " + text + "\n"
        case "title":
            body = calendar_body().replace("Internal standup", text)
        case "subject":
            body = progress_body().replace("Internal review", text)
    classified = classify_mail_candidate(candidate_for(body))
    assert classified.classification == "human_required"


@pytest.mark.parametrize(
    ("label", "email"),
    [pytest.param(label, email, id=label) for label, email in INVALID_EMAILS],
)
def test_malformed_address_is_not_a_contact(label: str, email: str) -> None:
    candidate = candidate_for(contact_body(email=email))
    classified = classify_mail_candidate(candidate)
    assert classified.classification == "human_required", (label, classified)


@pytest.mark.parametrize("body", [contact_body(), calendar_body(), progress_body()])
def test_explicit_internal_record_preserves_source_spans(body: str) -> None:
    candidate = candidate_for(body)
    classified = classify_mail_candidate(candidate)
    assert classified.classification == "auto_internal"
    assert all(
        body[span.start : span.end] == classified.fields[key]
        for key, span in classified.spans.items()
    )


@pytest.mark.parametrize(
    "body",
    [
        contact_body(name="김민수", email="minsu.kim+work@mail.internal"),
        contact_body() + "phone: +821012345678\ndepartment: Engineering\n",
        calendar_body().replace("Internal standup", "Internal review #project-alpha"),
        progress_body().replace("Internal review", "Internal note #project-alpha"),
        progress_body().replace("file the note", "내부 메모 정리"),
    ],
)
def test_explicit_data_formats_are_not_a_blanket_automation_ban(body: str) -> None:
    classified = classify_mail_candidate(candidate_for(body))
    assert classified.classification == "auto_internal"


def test_source_or_digest_change_cannot_grant_classification() -> None:
    candidate = candidate_for(progress_body())
    changed = (
        replace(candidate, source_system="unknown"),
        replace(candidate, content=contact_body()),
    )
    assert all(classify_mail_candidate(item).classification == "human_required" for item in changed)
