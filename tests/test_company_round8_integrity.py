from __future__ import annotations

import os
import signal
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest

import sb.company_auto_readback as readback
import sb.company_freshness_anchor as anchor
from sb.company_auto_engine import run_auto_internal
from sb.company_db_freshness_models import FreshnessRegistry
from sb.company_freshness_anchor import AnchorRejected
from sb.company_freshness_models import FreshnessScope, ReadFreshnessRequest
from sb.company_processor_progress import local_checkpoint
from sb.effect_values import canonical_bytes
from sb.effect_write_values import model_object
from tests.company_db_auto_support import real_company_runtime
from tests.company_internal_auto_support import PROVIDER, WORKSPACE, contact_body, receive, trigger


def rotate(provider):
    registry = FreshnessRegistry.model_validate_json(provider.registry_path.read_bytes())
    pin = registry.auto_policies[0].model_copy(update={"revision": 2})
    provider.registry_path.write_bytes(
        canonical_bytes(model_object(registry.model_copy(update={"auto_policies": [pin]})))
    )


def request(provider, checkpoint):
    return ReadFreshnessRequest(
        schema_version=2,
        scope=FreshnessScope(provider_instance_id=PROVIDER, workspace_id=WORKSPACE),
        installation_id=provider.installation_id,
        challenge="round8",
        observed_checkpoint=checkpoint,
    )


@pytest.mark.parametrize("fraction", [1, 2, 3])
def test_sigkill_torn_unpublished_witness_recovers(tmp_path: Path, fraction: int) -> None:
    provider, _, context = real_company_runtime(tmp_path)
    rotate(provider)
    scope = FreshnessScope(provider_instance_id=PROVIDER, workspace_id=WORKSPACE)
    path = provider.witness_dir / "frames.jsonl"
    before = path.read_bytes()
    pid = os.fork()
    if pid == 0:
        write = os.write

        def killed(fd, payload):
            write(fd, payload[: max(1, len(payload) * fraction // 4)])
            os.kill(os.getpid(), signal.SIGKILL)
            raise AssertionError("unreachable")

        anchor.os.write = killed
        provider.install_auto_policy_pin(scope)
        os._exit(99)
    _, status = os.waitpid(pid, 0)
    assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
    torn = path.read_bytes()
    assert torn.startswith(before) and not torn.endswith(b"\n")
    with pytest.raises((AnchorRejected, ValueError)):
        anchor.read_witness_frames(provider.witness_dir)
    with (
        pytest.raises((AnchorRejected, ValueError)),
        provider.read_only_report(scope),
    ):
        pass
    assert path.read_bytes() == torn
    response = provider.read_freshness(request(provider, context.observed_checkpoint))
    assert response.status == "mismatch"
    recovered = local_checkpoint(provider.database, WORKSPACE, None)
    assert recovered is not None and recovered != context.observed_checkpoint
    assert path.read_bytes().startswith(before)
    assert path.read_bytes().endswith(b"\n")
    assert provider.read_freshness(request(provider, recovered)).status == "ready"


@pytest.mark.parametrize(
    "damage", ["published_tail", "earlier_frame", "wrong_pending_prefix", "anchored_tail"]
)
def test_witness_damage_is_not_repaired(tmp_path: Path, damage: str, monkeypatch) -> None:
    provider, _, context = real_company_runtime(tmp_path)
    path = provider.witness_dir / "frames.jsonl"
    if damage in {"wrong_pending_prefix", "anchored_tail"}:
        rotate(provider)

        def fail(*args):
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")

        with monkeypatch.context() as fault:
            name = "append_witness_frame" if damage == "wrong_pending_prefix" else "save_checkpoint"
            fault.setattr("sb.company_db_freshness." + name, fail)
            with pytest.raises(AnchorRejected):
                provider.install_auto_policy_pin(request(provider, None).scope)
        if damage == "wrong_pending_prefix":
            path.write_bytes(path.read_bytes() + b'{"unrelated":')
        else:
            path.write_bytes(path.read_bytes()[:-10])
    elif damage == "published_tail":
        path.write_bytes(path.read_bytes()[:-10])
    else:
        raw = path.read_bytes()
        path.write_bytes(raw.replace(b'"checksum":"', b'"checksum":"f', 1))
    damaged = path.read_bytes()
    response = provider.read_freshness(request(provider, context.observed_checkpoint))
    assert response.status != "ready" and response.checkpoint is None
    assert path.read_bytes() == damaged


@pytest.mark.parametrize(
    "field,value", [("intent_root", "sha256:" + "ac" * 32), ("intent_sequence", 0)]
)
def test_policy_registration_rejects_forged_processor_checkpoint(tmp_path: Path, field, value):
    provider, _, context = real_company_runtime(tmp_path)
    rotate(provider)
    forged = context.observed_checkpoint.model_copy(update={field: value})
    with closing(sqlite3.connect(provider.database)) as db, db:
        db.execute(
            "UPDATE company_processor_checkpoint SET checkpoint_json=? WHERE workspace_id=?",
            (canonical_bytes(model_object(forged)).decode(), WORKSPACE),
        )
    before = (provider.witness_dir / "frames.jsonl").read_bytes()
    with pytest.raises(AnchorRejected):
        provider.install_auto_policy_pin(request(provider, None).scope)
    assert (provider.witness_dir / "frames.jsonl").read_bytes() == before
    assert local_checkpoint(provider.database, WORKSPACE, None) == forged


def test_completed_receipt_survives_unknown_classifier_version(tmp_path: Path, monkeypatch):
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "round8:mail", "round8:event", contact_body())
    result = run_auto_internal(provider.database, settings, context, provider, trigger())

    def changed(*args):
        raise AssertionError("historical unknown classifier must not be rerun")

    monkeypatch.setattr(readback, "classify_mail_candidate", changed)
    # A later release no longer implements the version carried by the old receipt.
    monkeypatch.setattr(readback, "CLASSIFIER_VERSION", "mail-classifier:future", raising=False)
    assert provider.read_freshness(request(provider, result.checkpoint)).status == "ready"
    with closing(sqlite3.connect(provider.database)) as db:
        receipt = db.execute("SELECT receipt_json FROM company_auto_policy_receipts").fetchone()[0]
        assessment = db.execute(
            "SELECT classifier_version FROM company_auto_assessments"
        ).fetchone()[0]
    assert assessment in receipt


def test_known_classifier_version_still_checks_classification(tmp_path: Path, monkeypatch):
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "round8:mail", "round8:event", contact_body())
    result = run_auto_internal(provider.database, settings, context, provider, trigger())
    classify = readback.classify_mail_candidate

    def changed(candidate):
        return replace(classify(candidate), classification="human_required")

    monkeypatch.setattr(readback, "classify_mail_candidate", changed)
    response = provider.read_freshness(request(provider, result.checkpoint))
    assert response.status != "ready" and response.checkpoint is None


@pytest.mark.parametrize("damage", ["source", "signature", "assessment_version", "payload"])
def test_unknown_classifier_never_bypasses_integrity(tmp_path: Path, monkeypatch, damage):
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "round8:mail", "round8:event", contact_body())
    result = run_auto_internal(provider.database, settings, context, provider, trigger())
    monkeypatch.setattr(readback, "CLASSIFIER_VERSION", "mail-classifier:future", raising=False)
    with closing(sqlite3.connect(provider.database)) as db, db:
        if damage == "source":
            db.execute("UPDATE company_memory_candidates SET content='altered original'")
        elif damage == "signature":
            db.execute("DROP TRIGGER company_auto_policy_receipts_no_update")
            db.execute(
                "UPDATE company_auto_policy_receipts SET receipt_json="
                "json_set(receipt_json,'$.signature','invalid')"
            )
        else:
            db.execute("DROP TRIGGER company_auto_assessments_no_update")
            if damage == "assessment_version":
                db.execute("UPDATE company_auto_assessments SET classifier_version='forged'")
            else:
                db.execute(
                    "UPDATE company_auto_assessments SET typed_payload_json="
                    "json_set(typed_payload_json,'$.fields.name','Forged Name')"
                )
    response = provider.read_freshness(request(provider, result.checkpoint))
    assert response.status != "ready" and response.checkpoint is None
