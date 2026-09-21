"""Application service coordinating validation, storage, export, and review."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Final, Literal, cast

from phone_history.config import Settings
from phone_history.errors import NotFoundError, ValidationError
from phone_history.models import EventBatch, PhoneEvent
from phone_history.redaction import redact_fields
from phone_history.repository import CandidateState, EventRecord, Repository
from phone_history.sink import DisabledSink, EventSink, SecondBrainSink, SinkError

_IDEMPOTENCY_RE: Final = re.compile(r"^[A-Za-z0-9._:-]{8,200}$")
CandidateDecision = Literal["queue_for_owner_review", "dismiss"]


@dataclass(frozen=True, slots=True)
class ServiceResponse:
    status: int
    payload: dict[str, object]


class PhoneHistoryService:
    def __init__(
        self,
        settings: Settings,
        *,
        repository: Repository | None = None,
        sink: EventSink | None = None,
    ) -> None:
        self.settings = settings
        self.repository = Repository(settings) if repository is None else repository
        if sink is not None:
            self.sink = sink
        elif settings.second_brain_vault is None:
            self.sink = DisabledSink()
        else:
            self.sink = SecondBrainSink(settings.second_brain_vault)

    def ingest(self, batch: EventBatch, *, idempotency_key: str) -> ServiceResponse:
        key = idempotency_key.strip()
        if _IDEMPOTENCY_RE.fullmatch(key) is None:
            raise ValidationError("Idempotency-Key must contain 8-200 safe characters")
        request_digest = batch.digest
        prior = self.repository.get_idempotency(key, request_digest)
        if prior is not None:
            replay = dict(prior.response)
            replay["replayed"] = True
            return ServiceResponse(status=200, payload=replay)

        accepted = 0
        already_present = 0
        event_results: list[dict[str, object]] = []
        for event in batch.events:
            candidate = self._candidate_payload(event)
            stored = self.repository.ingest_event(
                batch.device_id,
                event,
                candidate_payload=candidate,
            )
            if stored.state == "accepted":
                accepted += 1
            else:
                already_present += 1
            record = stored.event
            if record.sink_state == "pending":
                record = self._export(record)
            event_results.append(
                {
                    "id": record.id,
                    "state": stored.state,
                    "event_digest": record.event_digest,
                    "sink_state": record.sink_state,
                    "candidate_id": record.candidate_id,
                }
            )

        episode_count = self.repository.rebuild_episodes()
        response: dict[str, object] = {
            "schema_version": 1,
            "request_digest": request_digest,
            "replayed": False,
            "device_id": batch.device_id,
            "accepted": accepted,
            "already_present": already_present,
            "events": event_results,
            "episodes": episode_count,
            "canonicalized": 0,
            "approval_state": "owner_review_required",
        }
        self.repository.put_idempotency(
            key,
            request_digest,
            status=201,
            response=response,
        )
        return ServiceResponse(status=201, payload=response)

    def _export(self, record: EventRecord) -> EventRecord:
        try:
            sink_ref = self.sink.export(record)
        except Exception as exc:
            self.repository.mark_sink_pending(record.id, type(exc).__name__)
        else:
            self.repository.mark_sink_exported(record.id, sink_ref)
        return self.repository.get_event(record.id)

    def retry_pending(self, *, limit: int = 100) -> dict[str, int]:
        exported = 0
        pending = 0
        for record in self.repository.pending_events(limit=limit):
            refreshed = self._export(record)
            if refreshed.sink_state == "exported":
                exported += 1
            else:
                pending += 1
        return {"exported": exported, "pending": pending}

    def maintenance(self) -> dict[str, object]:
        retry = self.retry_pending(limit=500)
        pruned = self.repository.prune_expired_attachments()
        episodes = self.repository.rebuild_episodes()
        return {
            "schema_version": 1,
            "second_brain": retry,
            "attachments_pruned": pruned,
            "episodes": episodes,
            "canonicalized": 0,
        }

    def timeline(
        self,
        *,
        device_id: str | None = None,
        date: str | None = None,
        limit: int = 100,
    ) -> tuple[dict[str, object], ...]:
        return tuple(
            event.as_dict()
            for event in self.repository.timeline(device_id=device_id, date=date, limit=limit)
        )

    def episodes(self, *, limit: int = 100) -> tuple[dict[str, object], ...]:
        return self.repository.episodes(limit=limit)

    def candidates(
        self, *, state: str | None = None, limit: int = 100
    ) -> tuple[dict[str, object], ...]:
        allowed = {"unreviewed", "queued_for_owner_review", "dismissed"}
        if state is not None and state not in allowed:
            raise ValidationError("candidate state is invalid")
        chosen = None if state is None else cast(CandidateState, state)
        return tuple(
            candidate.as_dict()
            for candidate in self.repository.candidates(state=chosen, limit=limit)
        )

    def decide_candidate(self, candidate_id: str, decision: str) -> dict[str, object]:
        if decision not in {"queue_for_owner_review", "dismiss"}:
            raise ValidationError("candidate decision is invalid")
        record = self.repository.decide_candidate(
            candidate_id,
            cast(CandidateDecision, decision),
        )
        result = record.as_dict()
        result["canonical"] = False
        result["approval_effect"] = "none"
        return result

    def delete_event(self, event_id: str, *, reason: str) -> dict[str, object]:
        try:
            record = self.repository.get_event(event_id)
        except NotFoundError:
            record = None
        upload_id = _upload_id(None if record is None else record.sink_ref)
        if upload_id is not None:
            try:
                self.sink.retract(upload_id)
            except (SinkError, OSError, TimeoutError, ConnectionError) as exc:
                code = str(exc) or type(exc).__name__
                if record is not None:
                    self.repository.mark_sink_pending(record.id, code)
                return {
                    "state": "pending",
                    "event_digest": None,
                    "canonical_effect": "none",
                    "second_brain_retract": code,
                }
        result = self.repository.delete_event(event_id, reason=reason)
        return {**result.as_dict(), "canonical_effect": "none"}

    def status(self) -> dict[str, object]:
        return {
            **self.repository.status(),
            "version": "0.1.0-predevice",
            "device_closure": "NOT_RUN",
            "second_brain_configured": self.settings.second_brain_vault is not None,
        }

    def capabilities(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "version": "0.1.0-predevice",
            "capture": {
                "manual": True,
                "share_extension": True,
                "app_intents": True,
                "adot_shared_audio": True,
                "global_screen_recording": False,
                "global_keystroke_capture": False,
                "private_browsing_capture": False,
            },
            "limits": {
                "batch_events": 100,
                "attachment_bytes": 10 * 1024 * 1024,
                "request_bytes": self.settings.max_request_bytes,
            },
            "memory": {
                "second_brain_inbox_only": True,
                "auto_pipeline_run": False,
                "auto_approval": False,
                "canonicalization": False,
            },
            "device_closure": "NOT_RUN",
        }

    @staticmethod
    def _candidate_payload(event: PhoneEvent) -> dict[str, object] | None:
        fields, redaction_count, risk_flags = redact_fields(
            event.title,
            event.body,
            event.url,
            event.project_hint,
        )
        title, body, url, project_hint = fields
        attachment_name = event.attachment.filename if event.attachment is not None else ""
        content_parts = [part for part in (body, url, attachment_name) if part]
        if not title and not content_parts:
            return None
        return {
            "title": title or event.event_type.replace("_", " ").title(),
            "content": "\n\n".join(content_parts),
            "project_hint": project_hint,
            "risk_flags": list(risk_flags),
            "redaction_count": redaction_count,
            "knowledge_status": "UNVERIFIED",
            "approval_status": "UNREVIEWED",
            "canonical": False,
        }


def _upload_id(sink_ref: str | None) -> str | None:
    if sink_ref is None:
        return None
    try:
        payload = json.loads(sink_ref)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    upload_id = payload.get("upload_id")
    if isinstance(upload_id, str) and upload_id:
        return upload_id
    return None
