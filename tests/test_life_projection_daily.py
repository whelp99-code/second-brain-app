"""Daily projection order, flat event properties, and shared surface generation."""

from __future__ import annotations

import re
from datetime import timedelta

import yaml

from sb.effect_values import JsonObject, JsonValue
from sb.life_api_reads import aligned_surfaces
from sb.life_config import policy_for
from sb.life_contracts import LifeEventV1
from sb.life_http import LifeActor
from sb.life_journal_contracts import EvidenceRef, JournalRow
from sb.life_projection import project
from sb.life_relations import add as add_relation
from sb.life_values import parse_event
from sb.life_views import DAILY_SECTIONS, obsidian_manifest
from sb.store.ledger import Ledger
from sb.store.life_journal import LifeJournal
from tests.life_test_support import json_object
from tests.test_life_contracts import NOW, payload, policy
from tests.test_life_pipeline import life_config

DAY = "2026-09-26"
TZ = "Asia/Seoul"


def _frontmatter(content: str) -> dict[str, JsonValue]:
    text = content.split("---", 2)[1]
    loaded = yaml.safe_load(text)
    assert isinstance(loaded, dict)
    return json_object(loaded)


def _evidence(event: LifeEventV1) -> EvidenceRef:
    return {
        "event_id": event.event_id,
        "revision": event.revision,
        "raw_digest": event.raw_digest,
        "source_id": event.source_id,
        "policy_revision": event.policy_revision,
    }


def _relation(
    event: LifeEventV1,
    *,
    kind: str,
    from_id: str,
    to_id: str,
    state: str,
    level: str,
    valid_from: str | None,
    valid_until: str | None,
    evidence: list[EvidenceRef],
) -> JournalRow:
    body: JsonObject = {
        "relation_kind": kind,
        "from_id": from_id,
        "to_id": to_id,
        "state": state,
        "evidence_level": level,
        "valid_from": valid_from,
        "valid_until": valid_until,
    }
    return {
        "object_id": "relation:" + kind + ":" + from_id + ":" + to_id,
        "kind": "relation",
        "revision": 1,
        "body": body,
        "scopes": list(event.scopes),
        "source_ids": [event.source_id],
        "evidence": evidence,
        "recorded_at": event.recorded_at,
    }


def test_daily_sections_follow_spec_order():
    event = parse_event(payload(), policy(), recorded_at=NOW)
    view = obsidian_manifest((event,), day=DAY, timezone=TZ)
    daily = next(row["content"] for row in view["files"] if row["path"] == f"Auto/Daily/{DAY}.md")
    found = re.findall(r"^## (.+)$", daily, flags=re.MULTILINE)
    assert found == list(DAILY_SECTIONS)
    assert found == [
        "요점",
        "시간순",
        "결정 변화",
        "내일 필요한 기억",
        "중요한 빈칸",
        "MyNotes",
        "수집 상태",
    ]


def test_event_page_flat_properties_include_generation_timezone_evidence_count_and_links():
    event = parse_event(
        payload(entities=[{"entity_id": "ada", "kind": "person", "label": "Ada"}]),
        policy(),
        recorded_at=NOW,
    )
    view = obsidian_manifest((event,), day=DAY, timezone=TZ, evidence_counts={event.event_id: 2})
    page = next(row["content"] for row in view["files"] if row["path"].startswith("Auto/Events/"))
    meta = _frontmatter(page)
    assert meta["sb_generation"] == view["source_generation"]
    assert meta["sb_timezone"] == TZ
    assert meta["sb_evidence_count"] == 2
    links = meta["sb_links"]
    assert isinstance(links, list)
    assert links
    assert all(isinstance(link, str) and link.startswith("[[") for link in links)
    assert "generation" in "".join(meta)
    assert "timezone" in "".join(meta)
    assert "evidence_count" in "".join(str(meta))
    assert "links" in "".join(meta)


def test_nested_metadata_absent_from_frontmatter():
    event = parse_event(payload(), policy(), recorded_at=NOW)
    view = obsidian_manifest((event,), day=DAY, timezone=TZ)
    page = next(row["content"] for row in view["files"] if row["path"].startswith("Auto/Events/"))
    meta = _frontmatter(page)

    def walk(value: JsonValue) -> None:
        assert not isinstance(value, dict)
        if isinstance(value, list):
            for item in value:
                walk(item)

    for value in meta.values():
        walk(value)


def test_relations_projection_grouped_by_kind_with_evidence_and_validity():
    event = parse_event(payload(), policy(), recorded_at=NOW)
    cited = [_evidence(event)]
    workflows: dict[str, list[JournalRow]] = {
        "relation": [
            _relation(
                event,
                kind="works_at",
                from_id="people:ada",
                to_id="org:lab",
                state="asserted",
                level="user_asserted",
                valid_from="2026-01-01T00:00:00+09:00",
                valid_until="2026-12-31T00:00:00+09:00",
                evidence=cited,
            ),
            _relation(
                event,
                kind="knows",
                from_id="people:ada",
                to_id="people:bob",
                state="candidate",
                level="inferred",
                valid_from=None,
                valid_until=None,
                evidence=cited,
            ),
            _relation(
                event,
                kind="knows",
                from_id="ghost",
                to_id="nobody",
                state="candidate",
                level="inferred",
                valid_from=None,
                valid_until=None,
                evidence=[],
            ),
        ]
    }
    view = project(
        (event,),
        day=DAY,
        timezone=TZ,
        sensitivities=("public", "personal"),
        complete=True,
        workflows=workflows,
    )
    text = next(row["content"] for row in view["files"] if row["path"] == "Auto/Relations.md")
    assert text.index("## knows") < text.index("## works_at")
    assert "ghost" not in text
    assert "효력:" in text
    assert "근거 사건" in text
    assert "2026-01-01" in text


def _actor():
    return LifeActor(("test-notes",), ("principal:owner",), client=True)


def _accept(store, pol, **changes):
    key = changes.pop("key")
    expected = changes.pop("expected_revision", None)
    return store.accept(payload(**changes), pol, key=key, now=NOW, expected_revision=expected)


def test_same_generation_after_correction_and_forget_across_timeline_relations_manifest(tmp_path):
    config, root = life_config(tmp_path)
    actor = _actor()
    pol = policy_for(config, "test-notes")
    person = {"entity_id": "people:ada", "kind": "person", "label": "Ada"}
    with Ledger(root) as ledger:
        store = ledger.life_store()
        kept = _accept(
            store,
            pol,
            key="kept",
            source_item_id="kept",
            title="유지",
            entities=[person],
        )
        dropped = _accept(
            store,
            pol,
            key="dropped",
            source_item_id="dropped",
            title="삭제대상",
            entities=[person],
        )
        events = store.events(scopes=actor.scopes, now=NOW, source_ids=actor.source_ids)
        add_relation(
            LifeJournal(store),
            {
                "from_id": kept.event_id,
                "to_id": "people:ada",
                "kind": "participated_in",
                "evidence_event_ids": [kept.event_id],
                "evidence_level": "user_asserted",
                "idempotency_key": "rel-kept",
            },
            events=events,
            scopes=actor.scopes,
            source_ids=actor.source_ids,
            now=NOW,
        )

    def surfaces():
        return aligned_surfaces(config, root, actor, day=DAY, timezone=TZ, now=NOW)

    before = surfaces()
    generation = before["timeline"]["generation"]
    assert generation
    assert before["relations"]["generation"] == generation == before["manifest"]["source_generation"]
    assert before["relations"]["revisions"][kept.event_id] == 1
    page = next(
        row["content"]
        for row in before["manifest"]["files"]
        if row["path"] == f"Auto/Events/{kept.event_id}.md"
    )
    assert _frontmatter(page)["sb_revision"] == 1
    assert _frontmatter(page)["sb_generation"] == generation
    assert any(event["event_id"] == kept.event_id and event["revision"] == 1 for event in before["timeline"]["events"])

    with Ledger(root) as ledger:
        store = ledger.life_store()
        _accept(
            store,
            pol,
            key="kept-fix",
            source_item_id="kept",
            source_version="v2",
            title="정정",
            body="정정된 본문",
            entities=[person],
            expected_revision=1,
        )
    corrected = surfaces()
    assert corrected["timeline"]["generation"] != generation
    assert (
        corrected["relations"]["generation"]
        == corrected["timeline"]["generation"]
        == corrected["manifest"]["source_generation"]
    )
    assert corrected["relations"]["revisions"][kept.event_id] == 2
    assert all(ref["revision"] == 2 for row in corrected["relations"]["items"] for ref in row["evidence"]) or not corrected["relations"]["items"]
    fixed = next(
        row["content"]
        for row in corrected["manifest"]["files"]
        if row["path"] == f"Auto/Events/{kept.event_id}.md"
    )
    assert _frontmatter(fixed)["sb_revision"] == 2
    assert _frontmatter(fixed)["sb_generation"] == corrected["timeline"]["generation"]
    timeline_rev = next(event["revision"] for event in corrected["timeline"]["events"] if event["event_id"] == kept.event_id)
    assert timeline_rev == 2

    with Ledger(root) as ledger:
        ledger.life_store().forget(
            dropped.event_id, scopes=actor.scopes, expected_revision=1, now=NOW + timedelta(minutes=1)
        )
    forgotten = surfaces()
    assert forgotten["timeline"]["generation"] != corrected["timeline"]["generation"]
    assert (
        forgotten["relations"]["generation"]
        == forgotten["timeline"]["generation"]
        == forgotten["manifest"]["source_generation"]
    )
    assert dropped.event_id not in forgotten["relations"]["revisions"]
    assert all(event["event_id"] != dropped.event_id for event in forgotten["timeline"]["events"])
    assert all(dropped.event_id not in row["path"] and dropped.event_id not in row["content"] for row in forgotten["manifest"]["files"])
    assert forgotten["relations"]["revisions"][kept.event_id] == 2
