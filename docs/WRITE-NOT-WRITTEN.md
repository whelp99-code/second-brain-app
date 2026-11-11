# Write tool outcomes

`sb_write_request` publishes a durable request only when the tool result is an acceptance (`kind: "accepted"`).

`sb_remember` is a different contract. Success is only `{"inbox_path": "<inbox-path>"}`. It does not return `kind: "accepted"`. `RememberRejected` and `ErasureError` stay plain tool errors (`content exceeds 1MB`, and the erasure text). Those are not the JSON delivery payload.

`sb_write_request` failures, and unexpected `sb_remember` failures, are one strict JSON object with no prefix inside the tool error message. The MCP client may prefix `Error executing tool <name>: `.

Before a durable file or an activated generation pointer exists:

```json
{"cause":"WRITE_REQUEST_INVALID","code":"WRITE_REQUEST_INVALID","delivery":"not_written","retryable":false,"schema_version":1,"written":false}
```

Uncatalogued pre-publish failures use `"code":"NOTHING_WRITTEN"` and put the exception class in `cause`.

After the file is linked, moved to `processing`/`receipts`, recorded in the request journal, or the generation pointer has switched, a later failure is not `NOTHING_WRITTEN`:

```json
{"code":"WRITTEN_WITH_FOLLOWUP_ERROR","delivery":"written","retryable":true,"written":true}
```

The object also includes `path` and, when known, `request_id` or `generation_id`. Retry the same request. Do not abandon it as undelivered.

If a lookup (`lstat`, directory read, or journal read) fails, or a prior delivery might already exist but cannot be confirmed, the outcome is unknown. Absence of a pending file is not proof that nothing was written.

```json
{"code":"WRITE_OUTCOME_UNKNOWN","delivery":"unknown","retry":"Retry the same request. Do not treat this as not delivered.","retryable":true,"written":null}
```

A remember page path is `inbox/<sha256(request id, normalized title, body)>-<slug>.md`. The body is stored unchanged. There is no in-content marker and no side retry file. The runtime contract requires two identical remembers without a shared id to be two pages. Pass the same `request_id` (`[0-9A-Za-z_-]{1,64}`) to retry that page: the same id, title, and body return that path (`WRITTEN` or `WRITTEN_WITH_FOLLOWUP_ERROR`) and never a second page. A different title or a different id is a different page. An omitted id is a new page, not a retry. Whitespace-only differences in the title are the same title. The outcome is decided only by observing that final path: expected bytes present means written; `ENOENT` means `NOTHING_WRITTEN`; a stat or read error means `WRITE_OUTCOME_UNKNOWN`. Which step raised is not evidence. Publication is an exclusive create (`os.link`, or `renameat2` `RENAME_NOREPLACE` if link cannot work). Sealed inbox modes are restored in `finally`. A failed restore is `INBOX_MODE_RESTORE_FAILED`, not `NOTHING_WRITTEN`.

Contract for JARVIS reconcile:

- `written: false` and `delivery: "not_written"` mean nothing was written. Conclude not delivered.
- `WRITTEN_WITH_FOLLOWUP_ERROR` and `WRITE_OUTCOME_UNKNOWN` are not `NOTHING_WRITTEN`. Do not close them as undelivered.
- Absence of this payload (transport drop, timeout, or `kind: accepted` on `sb_write_request`) is still uncertain.
