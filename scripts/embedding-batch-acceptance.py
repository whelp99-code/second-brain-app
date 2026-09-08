"""Compare the real encoder's separate batches with one generation-scoped process.

Run baseline and session sequentially with the same model/environment. Identical
input and float32 output hashes are required before comparing their timings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import resource
import struct
import subprocess
import tempfile
import time
from contextlib import nullcontext
from pathlib import Path
from typing import cast

from korean_search_evaluation import load_dataset  # pyright: ignore[reportImplicitRelativeImport]

from sb.embeddings import encoder_session, resolve_encoder


def source_hash(root: Path) -> str:
    return hashlib.sha256(b"".join(str(path.relative_to(root)).encode() + b"\0" + path.read_bytes() + b"\0"
                                  for path in sorted((root / "sb").rglob("*.py")))).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--mode", choices=("baseline", "session"), required=True)
    mode = cast(str, parser.parse_args().mode)
    repository = Path(__file__).resolve().parents[1]
    base = Path(tempfile.mkdtemp(prefix="sb-embedding-batches-"))
    print(f"Evidence directory: {base}", flush=True)
    dataset = load_dataset(cast(object, json.loads((repository / "tests/fixtures/korean_search_v1.json").read_bytes())))
    texts = tuple(document.body for document in dataset.documents) + tuple(case.query for case in dataset.cases) + (
        "", "   ", "\t\n", " leading and trailing ", "가나다", "한글\n두번째 줄", "Cafe\u0301", "你好世界", "emoji 🧠 기억")
    before = source_hash(repository)
    encoder = resolve_encoder()
    identity = encoder.identity
    digest = hashlib.sha256()
    batches: list[dict[str, object]] = []
    started = time.perf_counter()
    with encoder_session(encoder) if mode == "session" else nullcontext(encoder) as scoped:
        for offset in range(0, len(texts), 64):
            batch = texts[offset:offset + 64]
            begin = time.perf_counter()
            vectors = scoped.encode(batch)
            if len(vectors) != len(batch) or scoped.identity != identity:
                raise ValueError("batch count or identity changed")
            blob = b"".join(struct.pack("<1024f", *vector) for vector in vectors)
            digest.update(blob)
            batches.append({"offset": offset, "count": len(batch), "seconds": time.perf_counter() - begin,
                            "float32_sha256": hashlib.sha256(blob).hexdigest()})
    elapsed = time.perf_counter() - started
    if source_hash(repository) != before:
        raise ValueError("product source changed during measurement")
    result = {"state": "measured", "mode": mode,
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip(),
        "source_tree_sha256": before, "model_id": identity.model_id, "revision": identity.revision,
        "dim": identity.dim, "inputs": len(texts),
        "inputs_sha256": hashlib.sha256(json.dumps(texts, ensure_ascii=False).encode()).hexdigest(),
        "float32_sha256": digest.hexdigest(), "seconds": elapsed, "batches": batches,
        "max_child_rss_kib": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
        "limitations": ["synthetic 129-input batch comparison; not user quality or capacity acceptance",
                        "single sequential measurement per mode; not operational p95",
                        "query processes are unchanged; no claim of faster independent searches"]}
    _ = (base / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
