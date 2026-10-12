-- Run with sqlite3 -readonly -json COMPANY_DB < deploy/company-reader-drain.sql.
-- :observed_at is optional; bind an ISO instant for deterministic replay.
-- Counts across the company database, not the reader's narrower access fence.
WITH
clock AS (
    SELECT julianday(coalesce(:observed_at, 'now')) AS observed
),
received AS (
    SELECT workspace_id, candidate_id, min(julianday(created_at)) AS first_received
    FROM company_memory_receipts
    WHERE operation = 'receive'
    GROUP BY workspace_id, candidate_id
),
pending AS (
    SELECT r.first_received
    FROM company_memory_candidates AS c
    LEFT JOIN received AS r
        ON r.workspace_id = c.workspace_id AND r.candidate_id = c.candidate_id
    WHERE c.state IN ('candidate', 'accepted')
),
backlog AS (
    SELECT
        count(*) AS pending_total,
        count(*) FILTER (
            WHERE first_received BETWEEN observed - 1 AND observed
        ) AS pending_received_last_24h,
        count(*) FILTER (
            WHERE first_received IS NULL OR first_received > observed
        ) AS pending_age_unknown,
        min(first_received) FILTER (
            WHERE first_received <= observed
        ) AS oldest_pending
    FROM pending CROSS JOIN clock
),
states AS (
    SELECT
        count(*) FILTER (WHERE state = 'candidate') AS candidate_total,
        count(*) FILTER (WHERE state = 'accepted') AS accepted_total,
        count(*) FILTER (WHERE state = 'processed_complete') AS processed_total,
        count(*) FILTER (WHERE state = 'rejected') AS rejected_total
    FROM company_memory_candidates
),
receipts AS (
    SELECT
        count(*) FILTER (
            WHERE operation = 'receive'
                AND julianday(created_at) BETWEEN observed - 1 AND observed
        ) AS receive_receipts_last_24h,
        count(*) FILTER (
            WHERE operation = 'read'
                AND julianday(created_at) BETWEEN observed - 1 AND observed
        ) AS read_receipts_last_24h,
        count(*) FILTER (
            WHERE operation = 'accept'
                AND julianday(created_at) BETWEEN observed - 1 AND observed
        ) AS accept_receipts_last_24h,
        count(*) FILTER (
            WHERE operation = 'reject'
                AND julianday(created_at) BETWEEN observed - 1 AND observed
        ) AS reject_receipts_last_24h,
        count(*) FILTER (
            WHERE operation = 'mark_processed'
                AND julianday(created_at) BETWEEN observed - 1 AND observed
        ) AS processed_receipts_last_24h,
        count(*) FILTER (
            WHERE operation IN ('read', 'accept', 'reject', 'mark_processed')
        ) AS processing_receipts_total,
        count(*) FILTER (
            WHERE julianday(created_at) IS NULL OR julianday(created_at) > observed
        ) AS invalid_receipt_time_count
    FROM company_memory_receipts CROSS JOIN clock
)
SELECT
    strftime('%Y-%m-%dT%H:%M:%fZ', observed) AS observed_at,
    strftime('%Y-%m-%dT%H:%M:%fZ', observed - 1) AS window_start,
    CASE
        WHEN observed IS NULL THEN 'invalid_clock'
        WHEN pending_age_unknown > 0 OR invalid_receipt_time_count > 0 THEN 'unknown'
        WHEN oldest_pending <= observed - 1 THEN 'stale'
        WHEN pending_total > 0 THEN 'pending'
        ELSE 'clear'
    END AS monitor_state,
    backlog.pending_total,
    backlog.pending_received_last_24h,
    backlog.pending_age_unknown,
    strftime('%Y-%m-%dT%H:%M:%fZ', oldest_pending) AS oldest_pending_received_at,
    round((observed - oldest_pending) * 86400, 3) AS oldest_pending_age_seconds,
    states.*,
    receipts.*
FROM clock CROSS JOIN backlog CROSS JOIN states CROSS JOIN receipts;
