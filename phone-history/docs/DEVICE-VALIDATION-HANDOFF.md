# 폰 히스토리 실기기 검증 인수서

- 대상 버전: `0.1.0-predevice`
- 자동 실행: `scripts/physical_device_gate.sh`
- 최종 상태 기본값: `NOT_APPROVED`
- 원칙: 자동 build/test PASS만으로 실기기 Closure를 선언하지 않는다.

## A. 연결 전 준비

1. Mac에 최신 안정 Xcode와 XcodeGen을 설치한다.
2. iPhone을 케이블 또는 신뢰된 Wi-Fi debugging으로 연결한다.
3. iPhone에서 이 Mac을 신뢰하고 Developer Mode를 켠다.
4. 실행 환경변수 `PHONE_HISTORY_DEVELOPMENT_TEAM`에 10자리 Team ID를 지정한다. 소스 파일에는 Team ID를 기록하지 않는다.
5. Apple Developer의 App ID 두 개에 동일 App Group과 Keychain Sharing을 설정한다.
   - `com.blro.phonehistory`
   - `com.blro.phonehistory.share`
6. 서버에 HTTPS endpoint와 최소 24자 Bearer token을 준비한다.
7. 테스트용 A닷 통화 녹음 한 건, 일반 오디오 한 건, 비오디오 파일 한 건을 준비한다.

## B. 자동 Gate

UDID 확인:

```bash
xcrun devicectl list devices
```

실행:

```bash
cd phone-history
PHONE_HISTORY_DEVICE_UDID=<DEVICE-UDID> scripts/physical_device_gate.sh
```

자동 PASS 기준:

- 계약/라우트 재생성
- iOS 정적 보안 Gate
- Xcode project generation
- signed device build
- XCTest
- 앱 설치
- 앱 launch 요청
- evidence 디렉터리와 `result.json` 생성

`result.json`은 자동 Gate가 통과해도 `manual_result=PENDING`, `closure=NOT_APPROVED`로 남는다.

## C. 수동·관찰 Gate

각 항목은 Evidence 경로, 서버 event ID, 화면 캡처 또는 로그를 남긴다.

### D1. 최초 실행과 설정

입력:

- HTTPS 서버 URL
- Bearer token
- 기본 프로젝트 `phone-history-device-test`

기대:

- URL이 HTTPS가 아니면 저장 거부
- URL에 `user:password@`가 있으면 저장 거부
- 토큰 입력 후 필드가 비워지고 Keychain에만 유지
- 서버 미설정 상태에서도 일시정지·기본 프로젝트 저장 가능

판정: `PASS / FAIL`

### D2. 직접 메모 오프라인 보존

1. iPhone 네트워크를 끈다.
2. `DEVICE-OFFLINE-MARKER-<timestamp>` 메모를 저장한다.
3. 앱을 강제 종료하고 다시 연다.

기대:

- 로컬 대기 1건 표시
- 본문이 App Group 파일의 평문 검색으로 발견되지 않음
- 강제 종료 후에도 같은 event ID 유지

판정: `PASS / FAIL`

### D3. 연결 복구와 영수증 기반 삭제

1. 네트워크를 켠다.
2. 동기화를 누른다.
3. 서버 receipt와 DB를 확인한다.

기대:

- 서버에 사건 1건 생성
- receipt의 accepted/duplicate event ID와 로컬 ID 일치
- 확인된 항목만 로컬 큐에서 제거
- 같은 payload 재전송 시 서버 사건 수가 늘지 않음

판정: `PASS / FAIL`

### D4. 영수증 누락 안전성

테스트 server/proxy가 2xx와 빈 JSON을 반환하게 한다.

기대:

- 앱 상태에 `서버 영수증이 없어 로컬 큐를 보존` 표시
- 로컬 원본 삭제 0건
- 정상 서버 복구 후 idempotent 동기화

판정: `PASS / FAIL`

### D5. Safari 공유

1. Safari에서 일반 HTTPS 페이지를 연다.
2. 공유 → `폰 히스토리에 저장`.
3. 프로젝트와 메모를 입력한다.

기대:

- Share Extension이 빠르게 종료
- 앱 로컬 큐에 `webpage_saved`
- URL, host, 메모, 프로젝트 유지
- 제외 호스트로 등록한 사이트는 저장 거부

판정: `PASS / FAIL`

### D6. 텍스트·사진·일반 파일 공유

각각 공유 메뉴에서 저장한다.

기대:

- 텍스트: `text_shared`
- 사진/파일: `file_shared`
- filename, MIME, byte count, SHA-256 일치
- 10 MiB 초과 파일 거부
- provider 임시 평문 경로가 별도 보관되지 않음

판정: `PASS / FAIL`

### D7. A닷 통화 녹음

1. A닷에서 통화 녹음 한 건을 공유한다.
2. Share Extension에서 `A닷 통화 녹음=예`로 바꾼다.
3. 저장 후 서버와 Second Brain 후보를 확인한다.

기대:

- `source=adot_share`
- `event_type=call_recording_imported`
- `sensitivity=restricted`
- `user_declared_adot=true`
- 원본 SHA-256/size 일치
- Second Brain에는 원본 음성이 직접 기록되지 않고 evidence reference만 연결

부정검사:

- 비오디오 파일에서 A닷 토글 `예` → 저장 거부
- 일반 오디오에서 토글 `아니오` → 일반 `file_shared`
- 파일명에 `adot`이 있어도 토글 `아니오` → 통화로 자동 분류하지 않음

판정: `PASS / FAIL`

### D8. App Intents

Siri/Spotlight/단축어에서 실행한다.

- 폰 히스토리에 메모 저장
- 폰 작업 시작 기록
- 폰 히스토리 동기화

기대:

- 첫 두 동작은 `capture_mode=shortcut`으로 queue 저장
- 동기화 Intent는 앱을 열고 foreground sync 요청
- Intent 안에서 임의 background network 실행에 의존하지 않음

판정: `PASS / FAIL`

### D9. 잠금·재부팅 보호

1. 메모 한 건을 queue에 남긴다.
2. iPhone을 재부팅한다.
3. 첫 잠금해제 전 Share Extension/앱 접근을 관찰한다.
4. 잠금해제 후 다시 연다.

기대:

- 첫 unlock 전 Keychain/file protection으로 데이터 사용 불가 또는 지연
- unlock 후 정상 복호화
- 손상 파일로 오판하지 않음
- event ID와 SHA 유지

판정: `PASS / FAIL`

### D10. BackgroundTasks 복구

1. 자동 동기화를 켠다.
2. 네트워크를 끄고 기록한다.
3. 앱을 background로 보낸다.
4. 네트워크 복구 후 시스템 BGTask 또는 다음 앱 실행을 관찰한다.

기대:

- BGTask 실행 여부와 관계없이 큐 유실 없음
- BGTask 실행 시 최대 4 batch 처리
- 실행되지 않으면 다음 foreground에서 같은 큐 처리

BGTask가 정확한 시각에 실행되지 않았다는 이유만으로 FAIL 처리하지 않는다. 큐 복구가 실패하면 FAIL이다.

판정: `PASS / FAIL`

### D11. 삭제와 tombstone

1. 서버 타임라인 사건 한 건을 swipe 삭제한다.
2. DB row와 첨부 제거를 확인한다.
3. 동일 event ID payload를 다시 전송한다.

기대:

- tombstone 생성
- 동일 ID 재수집 차단
- Second Brain outbox/candidate가 부활하지 않음

판정: `PASS / FAIL`

### D12. Second Brain 안전성

A닷·웹·메모 사건의 candidate를 확인한다.

기대:

```text
knowledge_status=UNVERIFIED
approval_status=UNREVIEWED
canonical=false
source=phone_history
```

- 검토함 버튼은 검토 요청 또는 제외만 제공
- Phone History가 wiki/daily를 직접 쓰지 않음
- prompt-injection marker가 명령으로 실행되지 않음
- PII/secret redaction 결과와 evidence reference 존재

판정: `PASS / FAIL`

## E. 종료 판정

필수 최종 필드:

```yaml
PHONE_HISTORY_VERSION: 0.1.0-predevice
AUTOMATED_DEVICE_BUILD: PASS|FAIL
XCTEST: PASS|FAIL
APP_INSTALL: PASS|FAIL
APP_GROUP_KEYCHAIN_PARITY: PASS|FAIL
OFFLINE_RECOVERY: PASS|FAIL
SAFARI_SHARE: PASS|FAIL
FILE_PHOTO_SHARE: PASS|FAIL
ADOT_SHARE: PASS|FAIL
BACKGROUND_RECOVERY: PASS|FAIL
DELETE_TOMBSTONE: PASS|FAIL
SECOND_BRAIN_SAFETY: PASS|FAIL
PRIVACY_NEGATIVE_TESTS: PASS|FAIL
DEVICE_CLOSURE: READY|NOT_READY
EVIDENCE_PATH: <absolute path>
```

한 항목이라도 FAIL 또는 미실행이면 `DEVICE_CLOSURE=NOT_READY`다.
