import json
from datetime import datetime, timedelta

import pytest

from sb.request_executor import RequestExecutor
from sb.request_store import RequestStore
from sb.scoped_request_status import read_scoped_request_status
from sb.source_access import SourceAccess
from tests.test_scoped_request_execution import fixture


def setup_status(tmp_path, execute=True):
    raw, now, config, accepted = fixture(tmp_path)
    if execute:
        executor = RequestExecutor(config, scoped_authority=lambda _: True)
        try:
            assert executor.apply_once(worker="fixture:writer", now=now).state == "proved"
        finally:
            executor.close()
    scope = SourceAccess("principal:owner", ("project:shared-memory",), "policy:fixture")
    store = RequestStore(config.request_root, maintenance_only=True)
    return raw, now, config, accepted, scope, store


def test_status_survives_write_expiry_and_missing_receipt_without_mutation(tmp_path):
    raw, _now, config, accepted, scope, store = setup_status(tmp_path)
    try:
        receipt = config.request_root / "receipts" / f"{accepted.request_id}.json"
        expected = json.loads(receipt.read_text())
        receipt.unlink()
        later = datetime.fromisoformat(raw["expires_at"]) + timedelta(days=1)
        before = tuple(store.db.iterdump())
        result = read_scoped_request_status(store, raw, expected_provider=config.provider_instance_id,
            clock=lambda: later, resolve_scope=lambda _: scope)
        assert result["state"] == "proved"
        assert result["receipt"] == expected
        assert tuple(store.db.iterdump()) == before
        assert not receipt.exists()
        result["proof"]["head"] = "mutated response"
        assert read_scoped_request_status(store, raw, expected_provider=config.provider_instance_id,
            clock=lambda: later, resolve_scope=lambda _: scope)["receipt"] == expected
    finally:
        store.close()


@pytest.mark.parametrize("mode", ["owner", "project", "policy", "revoked", "final_revoked", "rewind", "proof", "identity", "future"])
def test_status_denies_wrong_scope_revocation_and_corruption(tmp_path, mode):
    raw, now, config, _accepted, scope, store = setup_status(tmp_path)
    try:
        if mode in ("owner", "project", "policy"):
            scope = SourceAccess("principal:other" if mode == "owner" else scope.owner,
                ("project:other",) if mode == "project" else scope.projects,
                "policy:other" if mode == "policy" else scope.policy_revision)
        if mode == "proof":
            store.db.execute("UPDATE requests SET proof_digest=?", ("sha256:" + "0" * 64,))
        if mode == "identity":
            store.db.execute("UPDATE requests SET scope_digest=?", ("sha256:" + "0" * 64,))
        if mode == "future":
            store.db.execute("UPDATE requests SET updated_at=?", ((now + timedelta(days=1)).isoformat(),))
        calls = 0
        def resolver(at):
            nonlocal calls
            calls += 1
            return None if mode == "revoked" or (mode == "final_revoked" and calls == 2) else scope
        def clock():
            return now - timedelta(seconds=1) if mode == "rewind" and calls else now
        with pytest.raises(ValueError):
            read_scoped_request_status(store, raw, expected_provider=config.provider_instance_id,
                clock=clock, resolve_scope=resolver)
    finally:
        store.close()


def test_pending_has_no_proof_and_authorized_project_superset_can_read(tmp_path):
    raw, now, config, _accepted, scope, store = setup_status(tmp_path, execute=False)
    try:
        result = read_scoped_request_status(store, raw, expected_provider=config.provider_instance_id,
            clock=lambda: now, resolve_scope=lambda _: SourceAccess(scope.owner,
                ("project:other", "project:shared-memory"), scope.policy_revision))
        assert result["state"] == "pending"
        assert "proof" not in result and "receipt" not in result
    finally:
        store.close()
