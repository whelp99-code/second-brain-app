# Write tool: nothing published

`sb_write_request` / `sb_remember` publish a durable request only when the tool result is an acceptance (`kind: "accepted"`).

If the tool fails before that publish, the tool error text is one strict JSON object:

```json
{"cause":"WRITE_REQUEST_INVALID","code":"WRITE_REQUEST_INVALID","delivery":"not_written","retryable":false,"schema_version":1,"written":false}
```

Uncatalogued failures use `"code":"NOTHING_WRITTEN"` and put the exception class in `cause`.

Contract for JARVIS reconcile:

- `written: false` and `delivery: "not_written"` mean nothing was written. Conclude not delivered. Do not stay in `reconciling`.
- Map that payload to outcome code `NOTHING_WRITTEN` (including when `code` is a catalogue rejection). Catalogue codes remain in `cause`.
- `NOTHING_WRITTEN` is a pre-delivery failure, same class as a start failure: the abandon-not-delivered path may close it without waiting for expiry.
- Absence of this payload (transport drop, timeout after dispatch, or `kind: accepted`) is still uncertain. Do not invent not-delivered from `SECOND_BRAIN_TOOL_ERROR` alone.
