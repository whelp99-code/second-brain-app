"""Additive life tables in the existing ingest ledger, not a second database."""

from __future__ import annotations

SCHEMA_VERSION = 1
STATEMENTS = (
    "CREATE TABLE IF NOT EXISTS life_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS life_events (event_id TEXT PRIMARY KEY,source_id TEXT NOT NULL,source_item_id TEXT NOT NULL,scope TEXT NOT NULL,sensitivity TEXT NOT NULL,current_revision INTEGER NOT NULL,published_revision INTEGER NOT NULL DEFAULT 0,deleted INTEGER NOT NULL DEFAULT 0,occurred_start TEXT,occurred_end TEXT,updated_at TEXT NOT NULL,UNIQUE(source_id,source_item_id))",
    "CREATE INDEX IF NOT EXISTS life_events_time ON life_events(scope,occurred_start,event_id)",
    "CREATE INDEX IF NOT EXISTS life_events_pending ON life_events(deleted,published_revision,current_revision)",
    "CREATE TABLE IF NOT EXISTS life_event_revisions (event_id TEXT NOT NULL,revision INTEGER NOT NULL,source_version TEXT NOT NULL,raw_hash TEXT NOT NULL,event_json TEXT NOT NULL,content_digest TEXT NOT NULL,recorded_at TEXT NOT NULL,PRIMARY KEY(event_id,revision))",
    "CREATE TABLE IF NOT EXISTS life_receipts (receipt_id TEXT PRIMARY KEY,client_id TEXT NOT NULL,idempotency_key TEXT NOT NULL,request_digest TEXT NOT NULL,operation TEXT NOT NULL,event_refs TEXT NOT NULL,accepted_at TEXT NOT NULL,UNIQUE(client_id,idempotency_key))",
    "CREATE TABLE IF NOT EXISTS life_evidence_links (event_id TEXT NOT NULL,revision INTEGER NOT NULL,page_id TEXT NOT NULL,record_id TEXT NOT NULL,record_digest TEXT NOT NULL,PRIMARY KEY(event_id,revision,record_id))",
    "CREATE TABLE IF NOT EXISTS life_tombstones (sequence INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT NOT NULL UNIQUE,source_id TEXT NOT NULL,scope TEXT NOT NULL,deleted_at TEXT NOT NULL,reason_hash TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS life_source_health (source_id TEXT PRIMARY KEY,state TEXT NOT NULL,last_seen TEXT,coverage_start TEXT,coverage_end TEXT,error_code TEXT,received INTEGER NOT NULL DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS life_questions (question_id TEXT PRIMARY KEY,event_id TEXT NOT NULL,event_revision INTEGER NOT NULL,scope TEXT NOT NULL,source_id TEXT NOT NULL,kind TEXT NOT NULL,prompt TEXT NOT NULL,state TEXT NOT NULL,created_at TEXT NOT NULL,day TEXT NOT NULL,response_receipt TEXT)",
    "CREATE INDEX IF NOT EXISTS life_questions_day ON life_questions(day,state)",
    "CREATE TABLE IF NOT EXISTS life_question_preferences (event_id TEXT PRIMARY KEY,mute INTEGER NOT NULL DEFAULT 0,next_ask_at TEXT)",
    "CREATE TABLE IF NOT EXISTS life_briefings (briefing_id TEXT PRIMARY KEY,day TEXT NOT NULL,slot TEXT NOT NULL,scope_digest TEXT NOT NULL,input_digest TEXT NOT NULL,body_json TEXT NOT NULL,created_at TEXT NOT NULL,state TEXT NOT NULL,UNIQUE(day,slot,scope_digest,input_digest))",
    "CREATE TABLE IF NOT EXISTS life_delivery (delivery_id TEXT PRIMARY KEY,briefing_id TEXT NOT NULL,channel TEXT NOT NULL,state TEXT NOT NULL,provider_id TEXT,attempts INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL,UNIQUE(briefing_id,channel))",
    "CREATE TABLE IF NOT EXISTS life_predictions (prediction_id TEXT PRIMARY KEY,target_id TEXT NOT NULL,scope TEXT NOT NULL,issued_at TEXT NOT NULL,input_cutoff_at TEXT NOT NULL,target_start TEXT NOT NULL,prediction_json TEXT NOT NULL,content_digest TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS life_prediction_actuals (prediction_id TEXT NOT NULL,revision INTEGER NOT NULL,actual_json TEXT NOT NULL,content_digest TEXT NOT NULL,recorded_at TEXT NOT NULL,PRIMARY KEY(prediction_id,revision))",
    "CREATE TABLE IF NOT EXISTS life_projection_acks (client_id TEXT PRIMARY KEY,generation TEXT NOT NULL,acked_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS life_model_budget (reservation_id TEXT PRIMARY KEY,day TEXT NOT NULL,scope TEXT NOT NULL,policy_digest TEXT NOT NULL,reserved_tokens INTEGER NOT NULL,reserved_cost INTEGER NOT NULL,state TEXT NOT NULL,actual_tokens INTEGER,actual_cost INTEGER,created_at TEXT NOT NULL)",
)

STATEMENTS += (
    "CREATE TRIGGER IF NOT EXISTS life_prediction_immutable BEFORE UPDATE ON life_predictions BEGIN SELECT RAISE(ABORT,'life_prediction_immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS life_actual_immutable BEFORE UPDATE ON life_prediction_actuals BEGIN SELECT RAISE(ABORT,'life_actual_immutable'); END",
)

STATEMENTS += (
    "CREATE TABLE IF NOT EXISTS life_sensor_cursors(stream_id TEXT PRIMARY KEY,source_id TEXT NOT NULL,kind TEXT NOT NULL,anchor TEXT NOT NULL,updated_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS life_sensor_batches(receipt_id TEXT PRIMARY KEY,source_id TEXT NOT NULL,kind TEXT NOT NULL,raw_hash TEXT NOT NULL,created_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS life_sensor_evidence(event_id TEXT NOT NULL,revision INTEGER NOT NULL,batch_hash TEXT NOT NULL,PRIMARY KEY(event_id,revision,batch_hash))",
)

STATEMENTS += (
    "CREATE TABLE IF NOT EXISTS life_import_evidence(event_id TEXT NOT NULL,revision INTEGER NOT NULL,source_id TEXT NOT NULL,document_id TEXT NOT NULL,raw_hash TEXT NOT NULL,PRIMARY KEY(event_id,revision,raw_hash))",
)
