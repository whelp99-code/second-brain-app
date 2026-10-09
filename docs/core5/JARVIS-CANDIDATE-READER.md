# Jarvis Mail candidate reader

The new path is not deployed or provisioned by this PR. Existing Mail credentials
and the status/doctor CLI broker remain unchanged.

`sb-company candidates --config CONFIG < REQUEST_JSON` accepts canonical JSON
`{"authority": SIGNED_AUTHORITY, "arguments": {"limit": 100, "offset": 0}}`.
Use the existing company authority v1 signature and request digest domains,
operation `list_candidates`, purpose `company_memory_read`. Limit is 1..1000;
offset is 0..2^63-1. The operator-owned config must restrict each reader key to
`operations=["list_candidates"]`, `source_systems=["mail"]`. Unscoped keys cannot
use this path. Two independent reader key IDs/public keys can use one reader
context. The principal/projects/policy/deletion fence must match the existing
Mail candidates; the agent/session can identify the Jarvis reader in its
separate trusted config.

The response contains `candidates` (candidate ID, source event ID, content digest),
`count` (all eligible rows), `limit`, and `offset`. Only Mail rows in `candidate`
state within the signed workspace/access/deletion fence are counted. Content,
locator data, accepted/rejected/processed records and other sources are not
returned. Count and page use one SQLite read transaction opened with `mode=ro`;
there is no schema initialization, receipt or data write. Missing DB fails closed.
Accept, confirm, receive, reject, processing and single-candidate read are denied
for these keys. The dedicated `candidates` action also denies mutation claims
even if an operator accidentally includes a legacy key in its config.

## Provisioning after ACCEPT

Install the separate `deploy/second-brain-company-reader.socket` and
`deploy/second-brain-company-reader@.service` templates as jm user units. The
existing broker units/permissions are not edited. The new socket inherits its
group from the existing spool directory; verify jarvis-svc can traverse that
directory and connect, without giving it access to the database or jm home.
Do not enable before the merged receiver/config are installed.

Create two new Ed25519 keys (never rotate the Mail key). Store reader-side key
and authority-template/config files with mode 0600, owned by jarvis-svc, below
`/var/lib/jarvis-svc/credentials/second-brain/candidate-reader-{1,2}/`, with 0700
directories. Store the jm-owned server config at
`~/.config/second-brain/company-memory/jarvis-reader/config.json` (0600). It points
to the existing company database but has only the two new trusted public keys
and their exact list-only scopes. Do not copy Mail's signing key or source bindings.

Jarvis connects to `/var/lib/jarvis-svc/spool/second-brain/company-reader.sock`,
sends one bounded canonical signed request, shuts down its write half, and reads
the JSON response until EOF. Timeout is 15 seconds. One verification must run
as jarvis-svc through the real socket: both reader accounts list/count succeed,
accept/confirm/receive fail, and Mail key/broker privileges remain unchanged.
This PR's isolated CLI tests do not claim operational jarvis-svc verification.

Migration memo (planned, not provisioned): server config above, two reader
credential directories above, `second-brain-company-reader.socket` and
`second-brain-company-reader@.service`, socket path above; no new TCP port or
DB role. Root performs Cursor ACCEPT, merge, issuance and activation later.
