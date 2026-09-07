"""Profile exact conflict candidates; --full includes 100,000 repeated-token units.

Synthetic lexical workload only, no LLM/storage or full pipeline claims.
"""
from __future__ import annotations

import argparse
import cProfile
import hashlib
import json
import platform
import pstats
import resource
import sys
import time
from pathlib import Path
from tempfile import mkdtemp
from typing import cast

from sb.conflict import LexicalMatch, lexical_top
from sb.contracts import Unit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    full = cast(bool, args.full)
    root = Path(mkdtemp(prefix="sb-conflict-capacity-"))
    repository = Path(__file__).resolve().parent.parent
    evidence: dict[str, object] = {"state": "running", "workspace": str(root),
        "full": full, "platform": platform.platform(), "python": sys.version,
        "source_tree_sha256": hashlib.sha256(b"".join(
            str(path.relative_to(repository)).encode() + b"\0" + path.read_bytes() + b"\0"
            for path in sorted((repository / "sb").rglob("*.py")))).hexdigest(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "limitations": ["synthetic repeated-token corpus, cProfile overhead included",
                        "not worst-case diverse-query complexity, LLM or full managed writes"]}
    results: list[dict[str, object]] = []
    print(f"Evidence directory: {root}", flush=True)
    try:
        for count in (64, 128, 256, 100000) if full else (64, 128, 256):
            units = [Unit(f"{i:064x}", f"{i:064x}", "0-1200", f"원본{i} " + "a " * 598,
                          f"load:{i}.md") for i in range(count)]
            profile = cProfile.Profile()
            started = time.perf_counter()
            profile.enable()
            matches = lexical_top(units, ())
            profile.disable()
            elapsed = time.perf_counter() - started
            assert matches == tuple(LexicalMatch("0" * 64, f"{i:064x}", 598.0) for i in range(1, 11))
            profile_path = root / f"lexical-{count}.prof"
            profile.dump_stats(profile_path)
            stats = pstats.Stats(profile)
            # pstats exposes untyped internal profile rows; retain only call counts.
            raw_stats = cast(dict[tuple[str, int, str], tuple[int, int, float, float, object]],
                             cast(object, vars(stats)["stats"]))
            score_calls = sum(row[1] for key, row in raw_stats.items()
                              if key[0].endswith("conflict_lexical.py") and key[2] == "_score")
            assert score_calls == 1
            row: dict[str, object] = {"units": count, "seconds": elapsed, "matches": len(matches),
                "score_builds": score_calls, "profile": str(profile_path),
                "process_peak_rss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "rss_unit": "bytes" if sys.platform == "darwin" else "KiB"}
            results.append(row)
            evidence["results"] = results
            print(json.dumps(row), flush=True)
            _ = (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        evidence["state"] = "passed"
    except BaseException as exc:
        evidence.update({"state": "failed", "failure": f"{type(exc).__name__}: {exc}"})
        raise
    finally:
        _ = (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    main()
