"""Predeclared synthetic Life recall fixtures and their expected revisions."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from sb.effect_values import JsonObject, JsonValue
from sb.life_contracts import SourcePolicyV1
from sb.store.life import LifeStore

NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)
PAST = datetime(2026, 9, 1, 10, tzinfo=UTC)
SCOPES = ("principal:owner", "project:alpha")
SOURCES = ("benchmark-notes", "benchmark-mail", "benchmark-calendar")
WORDS = (
    "가람",
    "나래",
    "다온",
    "라온",
    "마루",
    "바람",
    "사랑",
    "아람",
    "자람",
    "차오름",
    "카나리",
    "타래",
    "파랑",
    "하늘",
    "고운",
    "누리",
    "도담",
    "로담",
    "미리내",
    "보람",
    "소담",
    "여울",
    "지음",
    "초롱",
    "코스모",
    "토리",
    "푸름",
    "한울",
    "구름",
    "노을",
)


@dataclass(frozen=True, slots=True)
class Case:
    case_id: str
    category: str
    topic: str
    request: JsonObject
    expected: tuple[tuple[str, int], ...]
    split: str


def split(topic: str) -> str:
    value = int(sha256(topic.encode()).hexdigest()[:8], 16) % 10
    return "train" if value < 6 else "evaluation" if value < 8 else "holdout"


def policy(secret: bool = False, source: str | None = None) -> SourcePolicyV1:
    return SourcePolicyV1(
        source_id="secret-notes" if secret else source or SOURCES[0],
        scopes=("principal:other", "project:secret") if secret else SCOPES,
        enabled=True,
        allowed_types=("note_saved", "decision"),
        sensitivity="restricted" if secret else "personal",
        external_processing="local_only",
        retention_days=365,
        policy_revision="benchmark-v1",
    )


def seed(
    store: LifeStore,
    name: str,
    body: str,
    *,
    version: int = 1,
    at: datetime = PAST,
    event_type: str = "note_saved",
    secret: bool = False,
    change_reason: str | None = None,
    source: str | None = None,
) -> str:
    payload = {
        "source_item_id": name,
        "source_version": f"v{version}",
        "event_type": event_type,
        "title": name,
        "body": body,
        "occurred_start": at.isoformat(),
        "observed_at": at.isoformat(),
        "timezone": "Asia/Seoul",
        "time_precision": "exact",
        "event_status": "occurred",
        "evidence_level": "user_asserted" if version > 1 else "observed",
        "review_state": "confirmed" if version > 1 else "unreviewed",
    }
    if change_reason is not None:
        payload["change_reason"] = change_reason
    receipt = store.accept(
        payload,
        policy(secret, source),
        key=name + f":{version}",
        now=at,
        expected_revision=version - 1 if version > 1 else None,
    )
    return receipt.event_id


def corpus(store: LifeStore) -> list[Case]:
    cases: list[Case] = []

    def add(
        category: str,
        topic: str,
        query: str,
        expected: Sequence[tuple[str, int]],
        **request: JsonValue,
    ) -> None:
        cases.append(
            Case(
                f"{category}-{sum(c.category == category for c in cases) + 1:03}",
                category,
                topic,
                {"query": query, **request},
                tuple(expected),
                split(topic),
            )
        )

    # 60 exact searches across 30 independent fictional project topics.
    for i, name in enumerate(WORDS):
        topic = "exact:" + name
        eid = seed(
            store,
            name + " 시범프로젝트",
            f"{name} 네트워크 이전. 승인된 견적 문서의 관리 번호 DEMO-{i:03}. "
            + "담당자 표기는 검증용 가상 인물이다. 작업 항목은 백업 점검과 문서 정리다.",
        )
        add("exact", topic, f"DEMO-{i:03}", [(eid, 1)])
        add("exact", topic, name + " 네트워크", [(eid, 1)])
    # 50 Korean spacing/case cases; no claim to semantic paraphrase coverage.
    for i, name in enumerate(WORDS[:25]):
        topic = "korean:" + name
        eid = seed(
            store,
            name + " 연결정책",
            f"{name} 가상 실험의 세컨드 브레인 운영 지침. "
            + f"사용자 메모 보호와 원문 근거 연결을 확인한다. 영문 식별자는 ExampleCase{i:02}.",
        )
        add("korean", topic, name + " 세컨드브레인", [(eid, 1)])
        add("korean", topic, f"examplecase{i:02}", [(eid, 1)])
    # 60 temporal questions with pre-change and current source snapshots.
    for i, name in enumerate(WORDS[:20]):
        topic = "temporal:" + name
        key = name + " 일정결정"
        eid = seed(store, key, f"{name} 계획의 초기안은 구안{i:02}이다.", event_type="decision")
        _ = seed(
            store,
            key,
            f"{name} 계획의 현재안은 신안{i:02}이다.",
            version=2,
            at=PAST + timedelta(days=10),
            event_type="decision",
            change_reason="가상 사용자 일정 변경",
        )
        add(
            "temporal",
            topic,
            f"구안{i:02}",
            [(eid, 1)],
            as_of=(PAST + timedelta(days=1)).isoformat(),
        )
        add("temporal", topic, f"신안{i:02}", [(eid, 2)])
        add("temporal", topic, f"구안{i:02}", [])
    # 40 multi-source-document retrievals, maintaining both independent origins.
    for i, name in enumerate(WORDS[:20]):
        topic = "multiple:" + name
        one = seed(
            store,
            name + " 회의기록",
            f"연결시험{i:02} 가상 회의: {name} 일정 검토와 자료 전달을 논의했다.",
        )
        two = seed(
            store,
            name + " 후속기록",
            f"연결시험{i:02} 가상 후속: {name} 일정 변경과 자료 전달을 기록했다.",
            source=SOURCES[1],
        )
        three = seed(
            store,
            name + " 일정기록",
            f"연결시험{i:02} 가상 일정: {name} 자료 전달 미팅의 일정 기록.",
            source=SOURCES[2],
        )
        add("multiple", topic, f"연결시험{i:02}", [(one, 1), (two, 1), (three, 1)])
        add("multiple", topic, f"연결시험{i:02} 자료 전달", [(one, 1), (two, 1), (three, 1)])
    # 40 correction/deletion cases; original rows stay on disk while read paths
    # must exclude withdrawn or obsolete current content.
    for i, name in enumerate(WORDS[:10]):
        topic = "lifecycle:" + name
        eid = seed(store, name + " 정정기록", f"정정전{i:02} 가상 납기 기록")
        _ = seed(
            store,
            name + " 정정기록",
            f"정정후{i:02} 가상 납기 기록",
            version=2,
            at=PAST + timedelta(days=5),
            change_reason="원문 정정",
        )
        deleted = seed(store, name + " 폐기기록", f"삭제검증{i:02} 가상 기록")
        store.forget(deleted, scopes=SCOPES, expected_revision=1, now=PAST + timedelta(days=6))
        add("lifecycle", topic, f"정정전{i:02}", [])
        add("lifecycle", topic, f"정정후{i:02}", [(eid, 2)])
        add("lifecycle", topic, f"삭제검증{i:02}", [])
        add("lifecycle", topic, f"삭제검증{i:02}", [], as_of=(PAST + timedelta(days=1)).isoformat())
    for i, name in enumerate(WORDS):
        add("no_answer", "none:" + name, f"미기록회의{i:02} 확정 결과", [])
    for i, name in enumerate(WORDS[:20]):
        _ = seed(store, "기밀" + name, f"범위검증{i:02} 다른 소유자의 제한 기록", secret=True)
        add("scope", "secret:" + name, f"범위검증{i:02}", [])
    assert len(cases) == 300
    return cases
