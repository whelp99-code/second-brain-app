# 폰 히스토리 Predevice 검증 결과

- 결과: **FAIL**
- 생성 시각(UTC): `2026-09-04T12:47:06.352432+00:00`
- 호스트: `linux` / Python `3.14.4`
- Closure: **NOT_READY**
- 실기기 Gate: **PENDING**

## 자동 Gate

| Gate | 결과 | 로그 |
|---|---:|---|
| `generate-ios-contract` | FAIL | `evidence/generate-ios-contract.log` |
| `generate-ios-api-paths` | PASS | `evidence/generate-ios-api-paths.log` |
| `ruff-format` | PASS | `evidence/ruff-format.log` |
| `ruff-check` | FAIL | `evidence/ruff-check.log` |
| `pytest` | FAIL | `evidence/pytest.log` |
| `compileall` | PASS | `evidence/compileall.log` |
| `ios-static` | FAIL | `evidence/ios-static.log` |
| `bash-syntax` | PASS | `evidence/bash-syntax.log` |
| `git-diff-check` | PASS | `evidence/git-diff-check.log` |

## Python 회귀테스트

- tests: `35`
- failures: `1`
- errors: `0`
- skipped: `0`

## 판정

`PASS`이면 Ubuntu에서 재현 가능한 구현·계약·보안 Gate가 끝났으며 macOS Xcode/실기기 검증으로 넘길 수 있다. 이 문서는 iPhone 서명·설치·A닷 공유 완료를 의미하지 않는다.

실기기 결과는 `DEVICE-VALIDATION-HANDOFF.md` D1-D12와 `evidence/device-*/result.json`으로 별도 판정한다.
