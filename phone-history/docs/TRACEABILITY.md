# 폰 히스토리 요구사항 추적표

| ID | 요구사항 | 구현 | 자동 검증 | 실기기 검증 |
|---|---|---|---|---|
| PH-001 | 직접 메모·작업 기록 | `CaptureService.swift`, `CaptureView` | event contract XCTest | D2 |
| PH-002 | Safari URL·공유 텍스트 | `ShareViewController.swift` | share static Gate | D5 |
| PH-003 | 사진·문서·오디오 공유 | `ShareViewController.swift`, `PhoneAttachment` | attachment XCTest | D6 |
| PH-004 | A닷은 사용자 명시로만 분류 | A닷 toggle + audio validation | static user-declared Gate | D7 |
| PH-005 | 10 MiB 초과 선제 거부 | provider fileSize + `PhoneAttachment` | oversized XCTest | D6/D7 |
| PH-006 | 오프라인 저장 | `SecureEventQueue` | queue XCTest | D2 |
| PH-007 | 로컬 평문 미저장 | AES-GCM `.phq` | plaintext-marker XCTest | D2 |
| PH-008 | 암호문 변조 탐지 | AES-GCM AAD=event ID | bit-flip XCTest | D9 |
| PH-009 | 앱/확장 같은 키 | App Group + Keychain entitlements | entitlement parity static | D1/D9 |
| PH-010 | 동일 ID idempotency/conflict | queue SHA 비교 + server repository | queue/server tests | D3 |
| PH-011 | HTTPS·Bearer | `AppPreferences`, `APIClient` | URL XCTest + API tests | D1 |
| PH-012 | URL 자격증명 거부 | `setServerURL` | URL XCTest | D1 |
| PH-013 | 성공 ID만 queue 삭제 | `SyncService`, `SyncReceipt` | server/API tests | D3/D4 |
| PH-014 | 서버 장애 시 queue 보존 | `SyncService` | outage regression | D3/D10 |
| PH-015 | BGTask는 보조 수단 | `BackgroundTasks.swift` | source/static | D10 |
| PH-016 | 서버 암호화 저장 | `crypto.py`, `repository.py` | plaintext DB tests | D3 |
| PH-017 | 첨부 hash/size 재검증 | server models/service/vault | attachment server tests | D6/D7 |
| PH-018 | 삭제 tombstone | repository/service/API | deletion/reingest tests | D11 |
| PH-019 | Second Brain inbox-only | `sink.py` | sink boundary tests | D12 |
| PH-020 | 후보는 미검증·미승인·비canonical | service + iOS review UI | candidate/static tests | D12 |
| PH-021 | canonical 자동 승인 금지 | `PhoneEvent.swift`, review UI | static source Gate | D12 |
| PH-022 | prompt injection/PII 격리 | `redaction.py`, service | adversarial tests | D12 |
| PH-023 | 앱별 전역 감시 없음 | 최소 entitlement/API | privacy static Gate | D1-D12 |
| PH-024 | 호스트 제외 | preferences + capture validation | URL/core tests | D5 |
| PH-025 | 로컬·서버 개별 삭제 | SwiftUI + API | deletion tests | D11 |
| PH-026 | Siri/Spotlight/단축어 | `AppIntents.swift` | Xcode compile | D8 |
| PH-027 | 계약 drift 방지 | Schema/fixture/OpenAPI generators | predevice generators | D1 |
| PH-028 | 재현 가능한 Gate evidence | `run_predevice_gate.py`, Mac/device scripts | structured JSON/JUnit | B/E |

## 상태 규칙

- 구현 파일이 존재해도 자동 테스트가 실패하면 완료가 아니다.
- Ubuntu Gate PASS는 `READY_FOR_DEVICE_VALIDATION`이다.
- Xcode build만 PASS하고 수동 D1-D12가 미완료면 `DEVICE_CLOSURE=NOT_READY`다.
- Phone History는 Second Brain canonical 승인이나 Action Hub 승인을 대신하지 않는다.
