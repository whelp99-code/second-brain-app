#!/usr/bin/env python3
"""Render human-readable verification evidence from the structured gate report."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "evidence" / "predevice-gate-result.json"
OUTPUT = ROOT / "docs" / "PREDEVICE-VERIFICATION.md"


def main() -> int:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    checks = report.get("checks", [])
    rows = []
    for check in checks:
        state = "PASS" if check.get("passed") else "FAIL"
        rows.append(f"| `{check.get('name', '')}` | {state} | `{check.get('log', '')}` |")
    pytest = report.get("pytest", {})
    text = f"""# 폰 히스토리 Predevice 검증 결과

- 결과: **{report.get("result", "UNKNOWN")}**
- 생성 시각(UTC): `{report.get("generated_at", "")}`
- 호스트: `{report.get("host", {}).get("platform", "")}` / Python `{report.get("host", {}).get("python", "")}`
- Closure: **{report.get("closure", "UNKNOWN")}**
- 실기기 Gate: **{report.get("device_gate", {}).get("status", "PENDING")}**

## 자동 Gate

| Gate | 결과 | 로그 |
|---|---:|---|
{chr(10).join(rows)}

## Python 회귀테스트

- tests: `{pytest.get("tests", 0)}`
- failures: `{pytest.get("failures", 0)}`
- errors: `{pytest.get("errors", 0)}`
- skipped: `{pytest.get("skipped", 0)}`

## 판정

`PASS`이면 Ubuntu에서 재현 가능한 구현·계약·보안 Gate가 끝났으며 macOS Xcode/실기기 검증으로 넘길 수 있다. 이 문서는 iPhone 서명·설치·A닷 공유 완료를 의미하지 않는다.

실기기 결과는 `DEVICE-VALIDATION-HANDOFF.md` D1-D12와 `evidence/device-*/result.json`으로 별도 판정한다.
"""
    OUTPUT.write_text(text, encoding="utf-8")
    return 0 if report.get("result") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
