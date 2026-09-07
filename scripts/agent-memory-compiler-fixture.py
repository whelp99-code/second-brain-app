"""Synthetic acceptance compiler: cite exact input lines; no external model calls."""
from __future__ import annotations

import json
import re
import sys
from typing import cast


def main() -> None:
    prompt = sys.stdin.read()
    if "relation, confidence, rationale" in prompt:
        print(json.dumps({"relation": "unrelated", "confidence": 1,
                          "rationale": "서로 다른 합성 검증 자료"}, ensure_ascii=False))
        return
    match = re.search(r"\n슬롯: (.*?)\n슬롯:", prompt, re.DOTALL)
    if match is None:
        raise ValueError("not a compile fixture prompt")
    rows = cast(list[tuple[str, str]], re.findall(r"(?:^|\n)sid=([0-9a-f]{8})[^\n]*\n(.*?)(?=\nsid=|\Z)",
                      match.group(1), re.DOTALL))
    if not rows:
        raise ValueError("missing cited units")
    for sid, body in rows:
        for line in body.splitlines():
            if line.strip():
                print(f"{line.strip()} [^{sid}]")


if __name__ == "__main__":
    main()
