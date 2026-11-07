"""Company-namespace labels are searchable and stay out of personal recall."""

from __future__ import annotations

from datetime import UTC, datetime

from sb.life_contracts import SourcePolicyV1
from sb.life_recall import in_namespace, rank
from sb.life_values import parse_event

NOW = datetime(2026, 11, 5, 0, 0, tzinfo=UTC)
POLICY = SourcePolicyV1(
    "scratch-ilji",
    ("principal:owner",),
    True,
    ("decision",),
    "restricted",
    "local_only",
    30,
    "scratch-v1",
)


def event(entity_id: str, label: str, body: str = "본문에는 회사명이 없다"):
    return parse_event(
        {
            "source_item_id": "d01",
            "source_version": "v1",
            "event_type": "decision",
            "title": "판단",
            "body": body,
            "occurred_start": "2026-11-01T09:00:00+09:00",
            "timezone": "Asia/Seoul",
            "time_precision": "minute",
            "entities": [{"entity_id": entity_id, "kind": "company", "label": label}],
        },
        POLICY,
        recorded_at=NOW,
    )


def test_company_label_is_found_only_in_company_namespace() -> None:
    company = event("company:co-ilji", "일지테크")
    personal = event("person-owner", "대표", "개인 메모")

    assert in_namespace(company, "company")
    assert not in_namespace(company, "personal")
    assert in_namespace(personal, "personal")
    assert rank((company,), "일지테크") == (company,)
    assert rank((company,), "본문에없는별칭") == ()
    assert rank((personal, company), "일지테크")[0] is company
