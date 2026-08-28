# Capacity and performance plan

## Supported topology

Second Brain 1.0 supports one operator, one local Vault and one active writer. The file lock prevents concurrent pipeline writers. Search and read-only clients may operate while no write transaction is in progress, but this release does not claim distributed-writer support.

## Release regression baseline

The repository test suite creates a real Git-backed Vault with:

- 1,000 committed Markdown pages;
- Unicode/Korean page identifiers and search terms;
- a committed FTS5 search index refresh;
- a retention reference audit;
- a checksummed backup;
- restore into a new path;
- search-result comparison between original and restored Vaults.

This medium-scale regression runs on every release gate because it is fast enough for continuous verification.

## Full load evidence target

The 0.8.0 operational load harness targets the approved development-plan dataset:

- 5,000 source files;
- 100,000 normalized units;
- 10,000 committed pages;
- 1,000 conflict records;
- 100 consecutive scheduled or equivalent installed commands.

This is a validation dataset, not a product hard limit. Full-load results, environment and timings must be recorded in release evidence rather than inferred from unit tests.

## Resource controls

Current controls include:

- maximum source files, source bytes and single-file size in the safe filesystem layer;
- maximum new units and database rows per run;
- separate LLM-call caps for compile, conflict and briefing stages;
- a single-writer Vault lock;
- SQLite WAL mode, integrity checks and explicit migration status;
- commit-aware incremental search refresh;
- a 10 MiB operational metrics log retaining at most the newest 10,000 rows after rotation;
- backup file-count and byte budgets;
- request-body limits in the local web console.

## Metrics

`sb metrics --json` and `/api/metrics` expose only content-free operational measurements:

- command count;
- non-zero exit count;
- command distribution;
- average duration;
- p95 duration.

Prompts, source text, titles, paths, tokens and user content are not included in metrics rows.

## Operator sizing

Before production onboarding, measure:

1. daily source-file and byte growth;
2. normalized units per source type;
3. LLM latency and failure rate;
4. Vault and CAS growth;
5. backup size and restore duration;
6. search p95 after representative commits;
7. orphan count and invalid-CAS count;
8. available disk space at twice the expected active Vault plus retained backups.

Increase run caps only after observing stable memory, disk and recovery behavior. A larger source corpus should be onboarded in waves with backup and restore evidence after each wave.
