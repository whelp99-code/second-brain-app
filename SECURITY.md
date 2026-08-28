# Security model

## Supported trust boundary

Second Brain 1.0 is a single-user, single-Vault local system. The host operating-system account is the primary security boundary. It is not a public multi-user service.

## Defaults

- Vault initialization uses owner-only permissions.
- Source filesystem adapters reject path escape, symlink escape, hardlinks, unsafe ownership and unsafe write modes according to the configured filesystem policy.
- The web console binds to `127.0.0.1` by default.
- A non-loopback web bind is refused unless `SB_WEB_TOKEN` is present.
- When `SB_WEB_TOKEN` is present, every `/api/*` request requires `Authorization: Bearer <token>`.
- Original source bytes remain immutable in the content-addressed store. Prompt-time masking never rewrites the original CAS object.
- CAS deletion is disabled by default. `sb gc` is a dry-run; deletion requires both `--apply` and `--confirm`.

## LLM egress policy

Each source can define:

```toml
[[sources]]
id = "private-notes"
adapter = "markdown-vault"
root = "/approved/private-notes"
llm_policy = "local-only" # allow | deny | local-only
sensitive = "mask"       # mask | allow | deny
```

`llm_policy` has the following meaning:

- `allow`: the source may be included in prompts for the configured model.
- `deny`: the source must never enter an LLM prompt.
- `local-only`: the source may enter prompts only when the configured model is explicitly local.

When `[llm].external = true`, a source without an explicit `llm_policy` defaults to `deny`. When the model is local, the default is `allow`.

`sensitive` has the following meaning:

- `mask`: mask common credentials and personal identifiers in the prompt-bound copy.
- `allow`: transmit the normalized text without masking.
- `deny`: reject the prompt if sensitive content is detected.

The masker covers email addresses, bearer tokens, common secret assignments and private-key blocks. This is defense in depth, not a guarantee that every possible sensitive value can be recognized. High-risk sources should use `deny` or `local-only`.

## Web exposure

Remote access should be placed behind a TLS reverse proxy and an operating-system firewall. `SB_WEB_TOKEN` must be high entropy and stored in a mode-0600 environment file or a secret manager. The built-in server is an operator console and does not provide multi-user sessions, password recovery or granular RBAC.

## Backup and restore

Backups contain original source content and must be protected as sensitive data. A restore verifies the backup checksum and every manifest entry before replacing a destination. Restoring into a non-empty destination requires an explicit force option and preserves the previous destination when supported by the operation.

## Reporting a security issue

Do not include live credentials, customer records or original private documents in an issue. Record the affected version, a reproduction using synthetic data, impact, whether data left the host and any relevant configuration policy names.
