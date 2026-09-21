# 통합 수용 기록 — 2026-09-21

## 판정

통합 브랜치 `codex/integration-20260921`의 격리 릴리스는 JARVIS 공유 기억 수용 시나리오를 통과했다. 운영 `app/current`는 변경하지 않았다.

## 자동 검증

| 게이트 | 결과 | 근거 |
| --- | --- | --- |
| Second Brain 회귀 | PASS | `1950 passed, 2 skipped` |
| Second Brain Ruff | PASS | `uv run ruff check sb tests` |
| Phone History 테스트 | PASS | `36 passed` |
| Phone History 사전 디바이스 게이트 | PASS | 계약 생성, Ruff, pytest, compileall, 정적 보안, diff 검사 |
| 격리 릴리스 생성 | PASS | `de5f246a4c3a490ee469140774a4c67609008c9d` |
| JARVIS 공유 기억 수용 | PASS | `deploy/check-release-integration.py` |

JARVIS 수용 게이트는 다음을 실제로 확인했다.

- 통합 커밋 `8da1284799aa1ab97b12d811eeef58b07dce57b7`에서 릴리스를 생성했다.
- 격리 JARVIS artifact `/var/tmp/jarvis-artifact-195b1a7/source/dist`를 사용했다.
- 실제 TLS, 독립 verifier 프로세스, MCP admission, CLI execution을 통과했다.
- 유효 요청의 settlement 1회, 새 로그인 readback, 동일 generation, record 2건을 확인했다.
- 철회 중 admission 거부, 실행 전 철회, 만료 전 실행 실패를 확인했다.
- provider와 JARVIS 후보 inventory 변경이 없었다.
- `production_activated: false`로 운영 전환은 하지 않았다.

## 남은 외부 게이트

### iOS/macOS

현재 검증 호스트는 Ubuntu라 `swiftc`, `xcodebuild`, `xcodegen`, Apple Team 서명, 실제 iPhone을 제공하지 않는다. 따라서 다음은 미실행 상태로 남긴다.

- generic iOS 및 simulator Xcode build
- 앱/Share Extension 서명 및 설치
- Safari·Files·Photos·A닷 공유 동작
- 잠금/재부팅 protected-data 동작
- BGTask 예약 관찰

Phone History 사전 디바이스 게이트의 `READY_FOR_DEVICE_VALIDATION`은 위 항목을 실행할 macOS 장비로 넘길 수 있다는 뜻이며, 실기기 완료를 의미하지 않는다.

### basedpyright

전체 `sb tests` 실행 결과는 기존 저장소의 전역 부채로 `408 errors / 5279 warnings`이다. 이번 통합 변경 파일에 대한 별도 검사는 오류 0건이었다. 대표 전역 오류는 import cycle과 테스트 mock 타입 불일치이며, 이번 통합의 기능 회귀와 분리해 후속 정리 대상으로 남긴다.

## 운영 결론

자동 수용 게이트는 닫혔지만, iOS 실기기 검증과 basedpyright 전역 정리는 닫히지 않았다. 그러므로 이 커밋을 운영 `master` 또는 `app/current`로 전환하지 않는다. macOS 장비 검증과 타입 부채 정리 후 별도 전환 게이트를 실행한다.
