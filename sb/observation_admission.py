"""Durable K7 observation admission journal.

Journal directory: ``<vault>/.sb/observations/``. Bytes and the receipt are
replaced into place before ``admit`` or ``advance`` returns. There is no queue,
watcher, or thread; callers advance state explicitly.

Emitters are server-registered. ``config.raw["observation_emitters"]`` is a list
of trusted-manifest rows (``TrustedSourceManifest`` fields). Absent or empty
means every emitter is unregistered. A body cannot add itself to that list.

Idempotency key is the K1 observation id (identity digest, not payload bytes).
The same key and the same payload bytes return the stored receipt, including
after the first response was lost. The same key with different bytes is a
conflict and does not overwrite the journal.

States, in admission order: accepted_pending, processing, published,
searchable. failed and rejected are terminal exits from accepted_pending or
processing only. ``unknown`` is not a state and is not searchable. published
requires a git commit sha; searchable requires an index generation
(``sbgen:v1:`` + 64 hex, or a positive decimal generation).
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from sb.effect_values import canonical_bytes
from sb.personal_observation import (
    MAX_ENVELOPE_BYTES,
    ObservationError,
    TrustedSourceManifest,
    decode_observation,
)

STATES: tuple[str, ...] = (
    "accepted_pending",
    "processing",
    "published",
    "searchable",
    "failed",
    "rejected",
)
_FORWARD: dict[str, frozenset[str]] = {
    "accepted_pending": frozenset({"processing", "failed", "rejected"}),
    "processing": frozenset({"published", "failed", "rejected"}),
    "published": frozenset({"searchable"}),
    "searchable": frozenset(),
    "failed": frozenset(),
    "rejected": frozenset(),
}
_COMMIT_SHA = re.compile(r"[0-9a-f]{40}\Z|[0-9a-f]{64}\Z")
_INDEX_GENERATION = re.compile(r"sbgen:v1:[0-9a-f]{64}\Z|[1-9][0-9]{0,18}\Z")
_REASON = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_RECEIPT_ID = re.compile(r"[0-9a-f]{64}\Z")
_MANIFEST_FIELDS = frozenset({
    "emitter",
    "account_id",
    "root",
    "source_id",
    "namespace",
    "source_policy_revision",
    "external_processing",
})
_REQUIRED_MANIFEST = _MANIFEST_FIELDS - {"external_processing"}
_RECEIPT_FIELDS = frozenset({
    "receipt_id",
    "state",
    "emitter",
    "observation_id",
    "idempotency_key",
    "payload_sha256",
    "size",
    "proof",
    "proofs",
    "admitted_at",
})


class AdmissionError(ValueError):
    """Stable code in ``code`` and ``str(exc)``; never includes payload bytes."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ObservationReceipt:
    receipt_id: str
    state: str
    emitter: str
    observation_id: str
    idempotency_key: str
    payload_sha256: str
    size: int
    proof: str | None
    proofs: dict[str, str]
    admitted_at: str

    @property
    def searchable(self) -> bool:
        return is_searchable(self.state)

    def as_dict(self) -> dict[str, object]:
        return {
            "receipt_id": self.receipt_id,
            "state": self.state,
            "emitter": self.emitter,
            "observation_id": self.observation_id,
            "idempotency_key": self.idempotency_key,
            "payload_sha256": self.payload_sha256,
            "size": self.size,
            "proof": self.proof,
            "proofs": dict(self.proofs),
            "admitted_at": self.admitted_at,
        }


def is_searchable(state: str) -> bool:
    """True only for the searchable state. unknown, published, and absent are not."""
    return state == "searchable"


def observation_journal(root: Path) -> Path:
    """Return ``<vault>/.sb/observations`` without creating it."""
    return _vault(root) / ".sb" / "observations"


def admit(root: Path, payload: bytes, *, emitter: str, config: object) -> ObservationReceipt:
    """Persist payload bytes and an accepted_pending receipt, then return it."""
    if type(payload) is not bytes or not payload or len(payload) > MAX_ENVELOPE_BYTES:
        raise AdmissionError("PAYLOAD_INVALID")
    manifests = _manifests_for(config, emitter)
    observation = _bind(payload, emitter, manifests)
    receipt_id = _receipt_id(observation.observation_id)
    digest = hashlib.sha256(payload).hexdigest()
    with _locked(root) as journal:
        body = _body_path(journal, receipt_id)
        stored = _read_bytes(body)
        existing = _read_file(journal, receipt_id)
        if stored is not None and stored != payload:
            raise AdmissionError("OBSERVATION_CONFLICT")
        if existing is not None:
            if existing.payload_sha256 != digest or existing.size != len(payload):
                raise AdmissionError("OBSERVATION_CONFLICT")
            if existing.idempotency_key != observation.observation_id:
                raise AdmissionError("OBSERVATION_CONFLICT")
            if stored is None:
                _atomic_write(body, payload)
            return existing
        if stored is None:
            _atomic_write(body, payload)
        receipt = ObservationReceipt(
            receipt_id=receipt_id,
            state="accepted_pending",
            emitter=emitter,
            observation_id=observation.observation_id,
            idempotency_key=observation.observation_id,
            payload_sha256=digest,
            size=len(payload),
            proof=None,
            proofs={},
            admitted_at=observation.ingested_at,
        )
        _write_receipt(journal, receipt)
        return receipt


def read(root: Path, receipt_id: str) -> ObservationReceipt | None:
    """Return a stored receipt, or None when that id was never admitted."""
    if _RECEIPT_ID.fullmatch(receipt_id) is None:
        raise AdmissionError("RECEIPT_ID_INVALID")
    journal = observation_journal(root)
    if not journal.is_dir():
        return None
    return _read_file(journal, receipt_id)


def read_body(root: Path, receipt_id: str) -> bytes | None:
    """Return admitted payload bytes, or None when they were never stored."""
    if _RECEIPT_ID.fullmatch(receipt_id) is None:
        raise AdmissionError("RECEIPT_ID_INVALID")
    path = _body_path(observation_journal(root), receipt_id)
    return _read_bytes(path)


def advance(root: Path, receipt_id: str, state: str, *, proof: str) -> ObservationReceipt:
    """Move one receipt forward. published needs a commit sha; searchable a generation."""
    if state not in STATES or state == "accepted_pending":
        raise AdmissionError("STATE_INVALID")
    _check_proof(state, proof)
    if _RECEIPT_ID.fullmatch(receipt_id) is None:
        raise AdmissionError("RECEIPT_ID_INVALID")
    with _locked(root) as journal:
        current = _read_file(journal, receipt_id)
        if current is None:
            raise AdmissionError("RECEIPT_NOT_FOUND")
        if not is_searchable(current.state) and current.state not in STATES:
            raise AdmissionError("STATE_INVALID")
        if current.state == state:
            if current.proofs.get(state) != proof:
                raise AdmissionError("PROOF_CONFLICT")
            return current
        allowed = _FORWARD.get(current.state)
        if allowed is None or state not in allowed:
            raise AdmissionError("STATE_NOT_MONOTONIC")
        proofs = dict(current.proofs)
        proofs[state] = proof
        updated = ObservationReceipt(
            receipt_id=current.receipt_id,
            state=state,
            emitter=current.emitter,
            observation_id=current.observation_id,
            idempotency_key=current.idempotency_key,
            payload_sha256=current.payload_sha256,
            size=current.size,
            proof=proof,
            proofs=proofs,
            admitted_at=current.admitted_at,
        )
        _write_receipt(journal, updated)
        return updated


def _check_proof(state: str, proof: str) -> None:
    if type(proof) is not str or not proof:
        raise AdmissionError("PROOF_REQUIRED")
    if state == "published":
        if _COMMIT_SHA.fullmatch(proof) is None:
            raise AdmissionError("PROOF_INVALID")
        return
    if state == "searchable":
        if _INDEX_GENERATION.fullmatch(proof) is None:
            raise AdmissionError("PROOF_INVALID")
        return
    if _REASON.fullmatch(proof) is None:
        raise AdmissionError("PROOF_INVALID")


def _bind(payload: bytes, emitter: str, manifests: tuple[TrustedSourceManifest, ...]):
    last = "PAYLOAD_INVALID"
    for manifest in manifests:
        try:
            return decode_observation(
                payload,
                manifest,
                emitter=emitter,
                account_id=manifest.account_id,
                root=manifest.root,
            )
        except ObservationError as exc:
            last = str(exc)
    raise AdmissionError(last)


def _manifests_for(config: object, emitter: str) -> tuple[TrustedSourceManifest, ...]:
    if type(emitter) is not str or not emitter.strip() or emitter != emitter.strip():
        raise AdmissionError("EMITTER_UNREGISTERED")
    raw = getattr(config, "raw", None)
    if not isinstance(raw, Mapping):
        raise AdmissionError("EMITTER_UNREGISTERED")
    rows = raw.get("observation_emitters")
    if rows is None or rows == []:
        raise AdmissionError("EMITTER_UNREGISTERED")
    if not isinstance(rows, list):
        raise AdmissionError("EMITTER_REGISTRY_INVALID")
    matched: list[TrustedSourceManifest] = []
    for row in rows:
        if not isinstance(row, Mapping) or set(row) - _MANIFEST_FIELDS or not _REQUIRED_MANIFEST <= set(row):
            raise AdmissionError("EMITTER_REGISTRY_INVALID")
        if row.get("emitter") != emitter:
            continue
        try:
            matched.append(TrustedSourceManifest(
                emitter=str(row["emitter"]),
                account_id=str(row["account_id"]),
                root=str(row["root"]),
                source_id=str(row["source_id"]),
                namespace=str(row["namespace"]),
                source_policy_revision=str(row["source_policy_revision"]),
                external_processing=str(row.get("external_processing", "local_only")),
            ))
        except (ObservationError, TypeError) as exc:
            raise AdmissionError("EMITTER_REGISTRY_INVALID") from exc
    if not matched:
        raise AdmissionError("EMITTER_UNREGISTERED")
    return tuple(matched)


def _receipt_id(observation_id: str) -> str:
    return hashlib.sha256(
        b"second-brain/observation-receipt/v1\0" + observation_id.encode()
    ).hexdigest()


def _vault(root: Path) -> Path:
    vault = root.expanduser().resolve()
    if not vault.is_dir():
        raise AdmissionError("VAULT_INVALID")
    return vault


def _body_path(journal: Path, receipt_id: str) -> Path:
    return journal / "bodies" / receipt_id[:2] / receipt_id


def _receipt_path(journal: Path, receipt_id: str) -> Path:
    return journal / "receipts" / receipt_id[:2] / f"{receipt_id}.json"


@contextmanager
def _locked(root: Path) -> Iterator[Path]:
    vault = _vault(root)
    journal = vault / ".sb" / "observations"
    journal.mkdir(parents=True, exist_ok=True)
    journal.chmod(0o700)
    descriptor = os.open(journal / ".lock", os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield journal
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise AdmissionError("JOURNAL_IO_FAILED")
            view = view[written:]
        os.fsync(descriptor)
    except Exception:
        os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise
    os.close(descriptor)
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _write_receipt(journal: Path, receipt: ObservationReceipt) -> None:
    payload = canonical_bytes(receipt.as_dict())
    _atomic_write(_receipt_path(journal, receipt.receipt_id), payload)


def _read_bytes(path: Path) -> bytes | None:
    if not path.is_file():
        return None
    try:
        return path.read_bytes()
    except OSError as exc:
        raise AdmissionError("JOURNAL_UNREADABLE") from exc


def _read_file(journal: Path, receipt_id: str) -> ObservationReceipt | None:
    path = _receipt_path(journal, receipt_id)
    raw = _read_bytes(path)
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AdmissionError("RECEIPT_UNREADABLE") from exc
    if not isinstance(parsed, dict) or set(parsed) != _RECEIPT_FIELDS:
        raise AdmissionError("RECEIPT_UNREADABLE")
    if parsed["receipt_id"] != receipt_id or type(parsed["state"]) is not str:
        raise AdmissionError("RECEIPT_UNREADABLE")
    proofs = parsed["proofs"]
    if not isinstance(proofs, dict) or any(type(key) is not str or type(value) is not str for key, value in proofs.items()):
        raise AdmissionError("RECEIPT_UNREADABLE")
    proof = parsed["proof"]
    if proof is not None and type(proof) is not str:
        raise AdmissionError("RECEIPT_UNREADABLE")
    size = parsed["size"]
    if type(size) is not int or size < 0:
        raise AdmissionError("RECEIPT_UNREADABLE")
    return ObservationReceipt(
        receipt_id=receipt_id,
        state=parsed["state"],
        emitter=str(parsed["emitter"]),
        observation_id=str(parsed["observation_id"]),
        idempotency_key=str(parsed["idempotency_key"]),
        payload_sha256=str(parsed["payload_sha256"]),
        size=size,
        proof=proof,
        proofs=dict(proofs),
        admitted_at=str(parsed["admitted_at"]),
    )
