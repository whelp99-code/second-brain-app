from __future__ import annotations

import pytest

from sb.company_memory import CompanyMemoryError, CompanyMemoryStore
from sb.source_access import SourceAccess


def test_company_candidate_acceptance_is_separate_from_processing(tmp_path):
    scope = SourceAccess("principal:owner", ("project:company",), "policy:1")
    store = CompanyMemoryStore(tmp_path / "company.db")
    try:
        candidate = store.receive(
            candidate_id="mail:candidate:1", source_system="mail", source_locator="msg/1",
            source_event_id="event:1", content="회의 일정", parser_version="mail:1",
            locator={"kind": "message", "ordinal": 1}, access=scope,
            deletion=(2, "sha256:" + "a" * 64),
        )
        assert candidate.state == "candidate"
        accepted = store.accept(candidate.candidate_id, scope, (2, "sha256:" + "a" * 64))
        assert accepted.state == "accepted"
        complete = store.mark_processed(candidate.candidate_id, scope, (2, "sha256:" + "a" * 64))
        assert complete.state == "processed_complete"
    finally:
        store.close()


def test_company_candidate_never_completes_without_acceptance(tmp_path):
    scope = SourceAccess("principal:owner", ("project:company",), "policy:1")
    store = CompanyMemoryStore(tmp_path / "company.db")
    try:
        store.receive(
            candidate_id="crm:candidate:1", source_system="cwos", source_locator="work/1",
            source_event_id="event:1", content="업무", parser_version="cwos:1",
            locator={"kind": "work", "ordinal": 1}, access=scope,
            deletion=(0, "sha256:" + "0" * 64),
        )
        with pytest.raises(CompanyMemoryError, match="NOT_ACCEPTED"):
            store.mark_processed("crm:candidate:1", scope, (0, "sha256:" + "0" * 64))
    finally:
        store.close()


def test_company_candidate_requires_current_scope_and_deletion_fence(tmp_path):
    scope = SourceAccess("principal:owner", ("project:company",), "policy:1")
    store = CompanyMemoryStore(tmp_path / "company.db")
    try:
        store.receive(
            candidate_id="mail:candidate:2", source_system="mail", source_locator="msg/2",
            source_event_id="event:2", content="보안 자료", parser_version="mail:1",
            locator={"kind": "message", "ordinal": 1}, access=scope,
            deletion=(3, "sha256:" + "b" * 64),
        )
        with pytest.raises(CompanyMemoryError, match="TOMBSTONE"):
            store.get("mail:candidate:2", scope, (2, "sha256:" + "a" * 64))
        with pytest.raises(CompanyMemoryError, match="SCOPED"):
            store.get("mail:candidate:2", SourceAccess("principal:owner", ("project:other",), "policy:1"),
                      (3, "sha256:" + "b" * 64))
    finally:
        store.close()

