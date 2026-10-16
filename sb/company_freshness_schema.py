"""Canonical component DDL; pure schema data shared by both migrators."""

from typing import Final

FRESHNESS_SQL: Final = """
CREATE TABLE company_freshness_epochs (
    provider_instance_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    epoch INTEGER NOT NULL CHECK (epoch >= 1 AND epoch <= 9007199254740991),
    previous_epoch INTEGER NULL CHECK (previous_epoch IS NULL OR previous_epoch >= 1),
    previous_checkpoint_digest TEXT NULL,
    genesis_json TEXT NOT NULL CHECK (json_valid(genesis_json)),
    registry_binding_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (provider_instance_id, workspace_id, epoch)
);
CREATE TABLE company_freshness_scopes (
    provider_instance_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    epoch INTEGER NOT NULL,
    checkpoint_json TEXT NOT NULL CHECK (json_valid(checkpoint_json)),
    checkpoint_digest TEXT NOT NULL,
    last_global_sequence INTEGER NOT NULL CHECK (last_global_sequence >= 0),
    initialized_at TEXT NOT NULL,
    PRIMARY KEY (provider_instance_id, workspace_id),
    FOREIGN KEY (provider_instance_id, workspace_id, epoch)
        REFERENCES company_freshness_epochs(provider_instance_id, workspace_id, epoch)
);
CREATE TABLE company_freshness_log (
    global_sequence INTEGER PRIMARY KEY CHECK (global_sequence >= 1 AND global_sequence <= 9007199254740991),
    provider_instance_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    phase TEXT NOT NULL CHECK (phase IN ('bootstrap','reserve','finish','registry')),
    operation_id TEXT NULL,
    record_json TEXT NOT NULL CHECK (json_valid(record_json)),
    evidence_json TEXT NOT NULL CHECK (json_valid(evidence_json)),
    record_digest TEXT NOT NULL,
    previous_nv TEXT NOT NULL,
    next_nv TEXT NOT NULL,
    before_checkpoint_json TEXT NOT NULL,
    after_checkpoint_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (provider_instance_id, workspace_id, global_sequence)
);
CREATE TABLE company_freshness_publication (
    global_sequence INTEGER PRIMARY KEY REFERENCES company_freshness_log(global_sequence),
    published_at TEXT NOT NULL
);
CREATE TABLE company_freshness_operations (
    provider_instance_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    operation TEXT NOT NULL CHECK (operation IN (
        'decide_approve','decide_reject','accept','reject','complete','mark_processed','delete'
    )),
    actor_store TEXT NOT NULL CHECK (actor_store IN ('jarvis','second_brain')),
    event_digest TEXT NOT NULL,
    reservation_id TEXT NOT NULL,
    reserve_expected_json TEXT NOT NULL,
    reserved_checkpoint_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('reserved','finished')),
    finish_expected_json TEXT NULL,
    evidence_digest TEXT NULL,
    terminal_state TEXT NULL,
    finished_checkpoint_json TEXT NULL,
    created_at TEXT NOT NULL,
    finished_at TEXT NULL,
    PRIMARY KEY (provider_instance_id, workspace_id, operation_id),
    UNIQUE (provider_instance_id, workspace_id, reservation_id)
);
CREATE UNIQUE INDEX company_freshness_one_reserved
    ON company_freshness_operations(provider_instance_id, workspace_id)
    WHERE state = 'reserved';
CREATE TABLE company_freshness_evidence (
    provider_instance_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    store TEXT NOT NULL,
    stream TEXT NOT NULL CHECK (stream IN ('receipt','terminal','deletion','revocation')),
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    root TEXT NOT NULL,
    previous_root TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    source_digest TEXT NOT NULL,
    evidence_json TEXT NOT NULL CHECK (json_valid(evidence_json)),
    created_at TEXT NOT NULL,
    PRIMARY KEY (provider_instance_id, workspace_id, store, stream, sequence),
    UNIQUE (provider_instance_id, workspace_id, store, stream, source_record_id)
);
CREATE TRIGGER company_freshness_epochs_no_update
BEFORE UPDATE ON company_freshness_epochs
BEGIN
    SELECT RAISE(ABORT, 'epoch_immutable');
END;
CREATE TRIGGER company_freshness_epochs_no_delete
BEFORE DELETE ON company_freshness_epochs
BEGIN
    SELECT RAISE(ABORT, 'epoch_immutable');
END;
CREATE TRIGGER company_freshness_log_no_update
BEFORE UPDATE ON company_freshness_log
BEGIN
    SELECT RAISE(ABORT, 'log_immutable');
END;
CREATE TRIGGER company_freshness_log_no_delete
BEFORE DELETE ON company_freshness_log
BEGIN
    SELECT RAISE(ABORT, 'log_immutable');
END;
CREATE TRIGGER company_freshness_evidence_no_update
BEFORE UPDATE ON company_freshness_evidence
BEGIN
    SELECT RAISE(ABORT, 'evidence_immutable');
END;
CREATE TRIGGER company_freshness_evidence_no_delete
BEFORE DELETE ON company_freshness_evidence
BEGIN
    SELECT RAISE(ABORT, 'evidence_immutable');
END;
CREATE TRIGGER company_freshness_publication_no_update
BEFORE UPDATE ON company_freshness_publication
BEGIN
    SELECT RAISE(ABORT, 'publication_immutable');
END;
CREATE TRIGGER company_freshness_publication_no_delete
BEFORE DELETE ON company_freshness_publication
BEGIN
    SELECT RAISE(ABORT, 'publication_immutable');
END;
CREATE TRIGGER company_freshness_operation_identity
BEFORE UPDATE ON company_freshness_operations
WHEN OLD.operation_id != NEW.operation_id
    OR OLD.operation != NEW.operation
    OR OLD.actor_store != NEW.actor_store
    OR OLD.event_digest != NEW.event_digest
    OR OLD.reservation_id != NEW.reservation_id
    OR OLD.reserve_expected_json != NEW.reserve_expected_json
    OR OLD.created_at != NEW.created_at
BEGIN
    SELECT RAISE(ABORT, 'operation_identity');
END;
CREATE TRIGGER company_freshness_operation_finish_once
BEFORE UPDATE ON company_freshness_operations
WHEN OLD.state = 'finished'
BEGIN
    SELECT RAISE(ABORT, 'operation_finished');
END;
"""

INTERNAL_AUTO_SQL: Final = """
CREATE TABLE company_auto_policies (
    provider_instance_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    policy_version INTEGER NOT NULL CHECK (policy_version >= 1),
    policy_digest TEXT NOT NULL,
    policy_json TEXT NOT NULL CHECK (json_valid(policy_json)),
    installed_at TEXT NOT NULL,
    PRIMARY KEY (provider_instance_id, workspace_id, policy_version)
);
CREATE UNIQUE INDEX company_auto_policies_digest
    ON company_auto_policies(provider_instance_id, workspace_id, policy_digest);
CREATE TRIGGER company_auto_policies_no_update
BEFORE UPDATE ON company_auto_policies
BEGIN SELECT RAISE(ABORT, 'immutable auto policy'); END;
CREATE TRIGGER company_auto_policies_no_delete
BEFORE DELETE ON company_auto_policies
BEGIN SELECT RAISE(ABORT, 'immutable auto policy'); END;
CREATE TABLE company_auto_assessments (
    provider_instance_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    policy_digest TEXT NOT NULL,
    assessment_digest TEXT NOT NULL,
    classification TEXT NOT NULL CHECK (classification IN ('auto_internal','human_required')),
    reason_codes_json TEXT NOT NULL CHECK (json_valid(reason_codes_json)),
    typed_payload_json TEXT CHECK (typed_payload_json IS NULL OR json_valid(typed_payload_json)),
    created_at TEXT NOT NULL,
    PRIMARY KEY (provider_instance_id, workspace_id, candidate_id, content_digest, policy_digest)
);
CREATE TRIGGER company_auto_assessments_no_update
BEFORE UPDATE ON company_auto_assessments
BEGIN SELECT RAISE(ABORT, 'immutable auto assessment'); END;
CREATE TRIGGER company_auto_assessments_no_delete
BEFORE DELETE ON company_auto_assessments
BEGIN SELECT RAISE(ABORT, 'immutable auto assessment'); END;
CREATE TABLE company_candidate_execution_claims (
    provider_instance_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    path TEXT NOT NULL CHECK (path IN ('human','auto_internal')),
    workflow_request_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (provider_instance_id, workspace_id, candidate_id)
);
CREATE TRIGGER company_candidate_claims_no_update
BEFORE UPDATE ON company_candidate_execution_claims
BEGIN SELECT RAISE(ABORT, 'immutable execution claim'); END;
CREATE TRIGGER company_candidate_claims_no_delete
BEFORE DELETE ON company_candidate_execution_claims
BEGIN SELECT RAISE(ABORT, 'immutable execution claim'); END;
CREATE TABLE company_auto_policy_receipts (
    provider_instance_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    auto_request_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    policy_digest TEXT NOT NULL,
    assessment_digest TEXT NOT NULL,
    auto_command_json TEXT NOT NULL CHECK (json_valid(auto_command_json)),
    receipt_json TEXT NOT NULL CHECK (json_valid(receipt_json)),
    receipt_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (provider_instance_id, workspace_id, auto_request_id),
    UNIQUE (provider_instance_id, workspace_id, candidate_id, content_digest, policy_digest)
);
CREATE TRIGGER company_auto_policy_receipts_no_update
BEFORE UPDATE ON company_auto_policy_receipts
BEGIN SELECT RAISE(ABORT, 'immutable policy receipt'); END;
CREATE TRIGGER company_auto_policy_receipts_no_delete
BEFORE DELETE ON company_auto_policy_receipts
BEGIN SELECT RAISE(ABORT, 'immutable policy receipt'); END;
CREATE TABLE company_internal_pending_reserve (
    provider_instance_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    intent_json TEXT NOT NULL CHECK (json_valid(intent_json)),
    PRIMARY KEY (provider_instance_id, workspace_id)
);
CREATE TABLE company_internal_pending_finish (
    provider_instance_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    pending_json TEXT NOT NULL CHECK (json_valid(pending_json)),
    PRIMARY KEY (provider_instance_id, workspace_id)
);
CREATE TABLE company_internal_effects (
    provider_instance_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    auto_request_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    effect_digest TEXT NOT NULL,
    manifest_json TEXT NOT NULL CHECK (json_valid(manifest_json)),
    created_at TEXT NOT NULL,
    PRIMARY KEY (provider_instance_id, workspace_id, operation_id),
    UNIQUE (provider_instance_id, workspace_id, auto_request_id)
);
CREATE TRIGGER company_internal_effects_no_update
BEFORE UPDATE ON company_internal_effects
BEGIN SELECT RAISE(ABORT, 'immutable internal effect'); END;
CREATE TRIGGER company_internal_effects_no_delete
BEFORE DELETE ON company_internal_effects
BEGIN SELECT RAISE(ABORT, 'immutable internal effect'); END;
CREATE TABLE company_internal_records (
    provider_instance_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    record_id TEXT NOT NULL,
    record_kind TEXT NOT NULL CHECK (record_kind IN ('contact','calendar','progress')),
    entity_key TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    source_event_id TEXT NOT NULL,
    source_candidate_id TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    effect_operation_id TEXT NOT NULL,
    source_slot TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (provider_instance_id, workspace_id, record_id),
    UNIQUE (provider_instance_id, workspace_id, source_event_id, record_kind, source_slot),
    FOREIGN KEY (provider_instance_id, workspace_id, effect_operation_id)
        REFERENCES company_internal_effects(provider_instance_id, workspace_id, operation_id)
);
CREATE TRIGGER company_internal_records_no_update
BEFORE UPDATE ON company_internal_records
BEGIN SELECT RAISE(ABORT, 'immutable internal record'); END;
CREATE TRIGGER company_internal_records_no_delete
BEFORE DELETE ON company_internal_records
BEGIN SELECT RAISE(ABORT, 'immutable internal record'); END;
"""
