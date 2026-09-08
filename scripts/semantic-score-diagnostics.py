"""Read actual model cosine scores from an isolated Korean evaluation generation.

Queries are encoded in batches to inspect score distributions. This is not native
request latency, an independently held-out evaluation, or threshold calibration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import cast

from korean_search_evaluation import (  # pyright: ignore[reportImplicitRelativeImport]
    array,
    load_dataset,
    object_value,
)

from sb import embeddings
from sb.config import load_config
from sb.generation_integrity import load_verified_manifest
from sb.generation_vectors import vector_blob


def diagnose(evaluation: Path) -> dict[str, object]:
    raw = (evaluation / "dataset.json").read_bytes()
    dataset = load_dataset(cast(object, json.loads(raw)))
    root = Path(load_config(evaluation / "config.toml").vault_root).resolve()
    manifest = load_verified_manifest(root)
    database = root / ".sb/vectors.db"
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        model_id, revision, dim, count = cast(tuple[str, str, int, int], conn.execute(
            "SELECT model_id,revision,dim,row_count FROM vector_info").fetchone())
    encoder = embeddings.resolve_encoder()
    identity = embeddings.ModelIdentity(model_id, revision, dim)
    if encoder.identity != identity:
        raise ValueError("diagnostic query model differs from sealed document model")
    started = time.perf_counter()
    results: list[dict[str, object]] = []
    for offset in range(0, len(dataset.cases), 32):
        batch = dataset.cases[offset:offset + 32]
        encoded = encoder.encode(tuple(case.query for case in batch))
        if len(encoded) != len(batch) or encoder.identity != identity:
            raise ValueError("diagnostic encoder count or identity changed")
        for case, vector in zip(batch, encoded, strict=True):
            blob = vector_blob(vector, dim).hex()
            distance = "vec_distance_cosine(embedding,X'" + blob + "')"
            sql = ("PRAGMA query_only=ON;SELECT json_array(page_id,record_id,1.0-" + distance
                   + ") FROM record_vectors ORDER BY " + distance + ",page_id,record_id LIMIT 5;")
            ranked: list[dict[str, object]] = []
            for line in embeddings.run_vec_read_script(database, sql).split("\x1e"):
                if not line.strip():
                    continue
                row = array(cast(object, json.loads(line)))
                if (len(row) != 3 or not isinstance(row[0], str) or not isinstance(row[1], str)
                    or not isinstance(row[2], (float, int)) or isinstance(row[2], bool)
                    or not -1.000001 <= row[2] <= 1.000001):
                    raise ValueError("invalid diagnostic score")
                ranked.append({"page_id": row[0], "record_id": row[1], "cosine": row[2]})
            results.append({"id": case.id, "kind": case.kind, "query": case.query,
                            "expected": case.expected, "top": ranked})
    if load_verified_manifest(root) != manifest:
        raise ValueError("diagnostic generation changed")
    ranges: dict[str, dict[str, object]] = {}
    for kind in sorted({case.kind for case in dataset.cases}):
        scores: list[float] = []
        misses = 0
        for result in results:
            if result["kind"] != kind:
                continue
            expected = cast(tuple[str, ...], result["expected"])
            top = [object_value(value) for value in array(result["top"])]
            chosen = ([row for row in top if row["page_id"] in expected] if expected else top[:1])
            if chosen:
                scores.append(cast(float, chosen[0]["cosine"]))
            else:
                misses += 1
        ranges[kind] = {"count": len(scores), "no_scored_candidate": misses,
                        "min": min(scores) if scores else None, "max": max(scores) if scores else None}
    return {"state": "measured", "evaluation": str(evaluation), "dataset_id": dataset.id,
            "dataset_origin": dataset.origin, "dataset_sha256": hashlib.sha256(raw).hexdigest(),
            "model_id": model_id, "revision": revision, "dim": dim, "vector_count": count,
            "generation": manifest, "seconds": time.perf_counter() - started,
            "ranges": ranges, "rows": results,
            "limitations": ["batched real query embeddings; not request latency",
                            "cosine candidates only; no lexical/RRF or answer generation evaluation",
                            "observational diagnostic; not a blind validation set or selected production threshold"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--evaluation", required=True, type=Path)
    _ = parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = cast(Path, args.output)
    if output.exists():
        raise ValueError("diagnostic output already exists")
    result = diagnose(cast(Path, args.evaluation))
    with output.open("x") as stream:
        _ = stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(output), "ranges": result["ranges"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
