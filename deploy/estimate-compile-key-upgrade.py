"""Read-only count of compile work under page-bound keys; no model invocation."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from sb.compile import _group_by_page, compile_page_key
from sb.compile_sources import lineage_token
from sb.config import load_config
from sb.pipeline import _materialize
from sb.security import source_llm_policy
from sb.store import deriv_key
from sb.store.cas import ContentAddressedStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    config = load_config(args.config)
    root = Path(config.vault_root).resolve(strict=True)
    database = root / ".sb/ledger.db"
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        sources = db.execute("SELECT source_id,source_uri,content_hash,source_version FROM source_item").fetchall()
        states = dict(db.execute("SELECT deriv_key,status FROM derivation"))
        compile_states = dict(db.execute("SELECT deriv_key,status FROM derivation WHERE stage='compile'"))
        has_provenance = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='unit_provenance'"
        ).fetchone()
        provenance = {}
        if has_provenance is not None:
            provenance = {
                unit_id: SimpleNamespace(
                    parser_version=parser,
                    model_version=model,
                    normalizer_version=normalizer,
                    profile_revision=profile,
                )
                for unit_id, parser, model, normalizer, profile in db.execute(
                    "SELECT unit_id, parser_version, model_version, normalizer_version,"
                    " profile_revision FROM unit_provenance"
                )
            }
        by_stage = [
            {"stage": stage, "status": status, "count": count}
            for stage, status, count in db.execute(
                "SELECT stage,status,count(*) FROM derivation GROUP BY stage,status"
            )
        ]
    units = []
    missing = recorded_skips = 0
    cas = ContentAddressedStore(root)
    for source, uri, digest, version in sources:
        if not cas.exists(digest):
            missing += 1
            recorded_skips += int(hashlib.sha256(f"skip:{version}".encode()).hexdigest() == digest)
            continue
        data = cas.get(digest)
        if hashlib.sha256(data).hexdigest() != digest:
            raise RuntimeError("CAS_DIGEST_MISMATCH")
        units.extend(_materialize(data, digest, uri, f"{source}:{uri}"))
    groups = _group_by_page(units)
    counts = Counter()
    policy_counts = Counter()
    legacy_keys = []
    current_keys = set()
    done_invalidated = 0
    done_unchanged = 0
    prompt_version = config.llm.prompt_version
    model_id = config.llm.model_id

    class _Provenance:
        def provenance_for_unit(self, unit_id: str):
            return provenance.get(unit_id)

    recorded = _Provenance()
    for page, grouped in groups:
        ids = [unit.unit_id for unit in grouped]
        policies = {
            source_llm_policy(config, unit.origin.partition(":")[0] or "unknown")
            for unit in grouped
        }
        policy_counts["deny" if "deny" in policies else "llm"] += 1
        old = deriv_key(ids, "compile", prompt_version, model_id)
        production = deriv_key(
            ["compile-page-v1:" + page, *ids], "compile", prompt_version, model_id,
        )
        new = compile_page_key(
            page, ids, prompt_version, model_id, lineage=lineage_token(recorded, grouped),
        )
        current_keys.add(new)
        legacy_keys.append(old)
        state = states.get(new, "missing")
        counts[state] += 1
        if states.get(production) == "done" and new != production:
            done_invalidated += 1
        elif states.get(production) == "done":
            done_unchanged += 1
        if state in {"missing", "pending", "failed"} and states.get(old) == "done":
            counts["legacy_done_recompile"] += 1
    historical = Counter(status for key, status in compile_states.items() if key not in current_keys)
    eligible = sum(counts[state] for state in ("missing", "pending", "failed"))
    cap = config.caps["max_llm_calls_compile"]
    if hashlib.sha256(database.read_bytes()).hexdigest() != before:
        raise RuntimeError("READ_SNAPSHOT_CHANGED")
    print(
        json.dumps(
            {
                "vault_generation": root.name,
                "ledger_sha256": before,
                "source_rows": len(sources),
                "rows_without_cas": missing,
                "recorded_skip_rows_without_cas": recorded_skips,
                "unexplained_missing_cas_rows": missing - recorded_skips,
                "page_groups": len(groups),
                "distinct_legacy_keys": len(set(legacy_keys)),
                "new_key_states": dict(counts),
                "page_policy_counts": dict(policy_counts),
                "production_key_formula": "compile-page-v1:<page_id> + unit ids",
                "done_keys_invalidated": done_invalidated,
                "done_keys_unchanged": done_unchanged,
                "eligible_page_calls": eligible,
                "non_current_compile_states": dict(historical),
                "non_current_compile_unfinished": sum(historical[state] for state in ('pending', 'running', 'failed')),
                "compile_call_cap": cap,
                "minimum_runs_at_cap": (eligible + cap - 1) // cap if cap > 0 else None,
                "derivation_counts": by_stage,
                "model_calls_made": 0,
                "read_only": True,
                "limitations": "Successful-page call count only, not token/currency estimate; retries and failures may require more runs. Missing CAS rows include skips and require separate diagnosis.",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
