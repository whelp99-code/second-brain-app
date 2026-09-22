# 폰 히스토리 아키텍처

## 1. 구성

```text
iPhone
├─ PhoneHistory SwiftUI App
│  ├─ 오늘: 로컬 대기 + 서버 타임라인
│  ├─ 기록: 빠른 메모 + 작업 시작
│  ├─ 검토: UNVERIFIED 후보의 검토 요청/제외
│  └─ 설정: 서버·프로젝트·제외 호스트·삭제
├─ Share Extension
│  ├─ URL / text / image / file
│  └─ 사용자 명시형 A닷 오디오
├─ App Intents
│  ├─ 메모 저장
│  ├─ 작업 시작
│  └─ 앱을 열어 동기화
└─ App Group Secure Queue
   └─ one event = one AES-GCM .phq file

HTTPS + Bearer
    │
    ▼
Phone History Server
├─ strict PhoneEvent parser
├─ SHA-256 idempotency/dedup
├─ encrypted SQLite fields
├─ encrypted attachment vault
├─ tombstone deletion
├─ episode/candidate generation
└─ Second Brain inbox-only sink
    │
    ▼
Second Brain / JARVIS / Codex / ChatGPT
```

## 2. 계약 단일 원천

- 이벤트 필드: `contracts/phone-event-v1.schema.json`
- 정상 요청 예시: `contracts/fixtures/event-batch.json`
- HTTP 경로: `contracts/openapi.yaml`
- Swift 생성물: `ios/Core/GeneratedContract.swift`, `GeneratedAPIPaths.swift`

Swift 생성물은 손으로 수정하지 않는다. 다음 명령으로 다시 만든다.

```bash
python3 scripts/generate_ios_contract.py
python3 scripts/generate_ios_api_paths.py
```

fixture에는 서버가 요구하는 envelope 기본값이 남는다. 앱은 생성된 semantic field map으로 ID, 시각, 출처, 사건 종류, 본문, 프로젝트, 첨부를 변경한다. 첨부가 단일 객체인지 배열인지는 Schema에서 자동 결정한다.

## 3. 로컬 기록 흐름

```text
사용자 입력/공유
  → PhoneEventDraft
  → canonical fixture template 적용
  → 첨부 SHA-256 + base64 contract payload
  → canonical JSON SHA-256
  → record Codable
  → AES-GCM(queue key, AAD=event id)
  → App Group/PhoneHistory/Queue/<event-id>.phq
```

큐 key는 공유 Keychain access group에 `AfterFirstUnlockThisDeviceOnly`로 저장한다. 앱과 확장이 동일 key를 사용한다. `.phq` 파일에는 JSON 평문을 저장하지 않는다.

큐는 중앙 index를 쓰지 않고 이벤트마다 파일을 하나 사용한다. 앱과 확장이 동시에 저장해도 destination move가 원자적 충돌점이 된다. 기존 파일이 있으면 복호화 후 content SHA를 비교한다.

## 4. 동기화 흐름

```text
queue snapshot 최대 50건
  → fixture batch envelope 생성
  → HTTPS POST + Bearer token
  → 서버 이벤트별 receipt
  ├─ accepted/duplicate/already_present ID만 큐 삭제
  ├─ rejected ID는 큐 유지 + 사유 표시
  └─ 명시적 receipt 없음: 전체 큐 유지
```

네트워크 단절, 5xx, 앱 종료 시 큐는 유지된다. BGAppRefresh는 재시도 기회를 늘리는 보조 기능이다. 정확성은 앱 열기와 수동 동기화가 같은 큐를 다시 처리하는 것으로 보장한다.

## 5. 서버 저장과 삭제

- 이벤트 ID와 canonical content SHA로 idempotency를 판정한다.
- 동일 ID·동일 내용은 중복 성공으로 응답한다.
- 동일 ID·다른 내용은 conflict다.
- 본문과 민감 필드는 저장 전 암호화한다.
- 첨부는 SHA-256/size를 다시 확인하고 암호화 vault에 저장한다.
- 삭제는 DB row/첨부를 제거하고 tombstone을 남긴다.
- tombstone ID는 같은 이벤트의 재유입을 막는다.

## 6. Second Brain 연결

Phone History 서버 ledger가 모바일 사건의 원본이다. Second Brain으로는 검토 가능한 inbox 자료만 전달한다.

금지:

- Phone History 코드가 wiki나 daily 파일 직접 쓰기
- candidate를 canonical로 자동 승격
- 후보 본문 안의 명령 실행
- 삭제된 원본의 handoff 재생성

후보 기본값:

```yaml
knowledge_status: UNVERIFIED
approval_status: UNREVIEWED
canonical: false
source: phone_history
```

## 7. 장애 격리

| 장애 | 동작 |
|---|---|
| 서버 중단 | 암호화 로컬 큐 유지 |
| 토큰 오류 | 큐 유지, 설정 오류 표시 |
| 응답 영수증 누락 | 큐 유지, idempotent 재전송 |
| 큐 암호문 변조 | 해당 파일 corrupt 표시, 자동 삭제 안 함 |
| Second Brain 중단 | server outbox에 handoff 재시도 |
| JARVIS 중단 | 수집·서버 저장 계속 가능 |
| 공유 확장 시간 제한 | 네트워크 없이 로컬 큐 저장 후 종료 |

## 8. 빌드 경계

Ubuntu predevice Gate는 서버·계약·권한·Swift 구문을 검증한다. 실제 UIKit/Share Extension/서명은 macOS Xcode Gate가 소유한다.

```bash
python3 scripts/run_predevice_gate.py
scripts/mac_predevice_gate.sh
PHONE_HISTORY_DEVICE_UDID=<udid> scripts/physical_device_gate.sh
```

실기기 최종 결과는 자동 build/test와 수동 D1-D12 evidence가 모두 통과해야 한다.
