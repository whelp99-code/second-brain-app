# 폰 히스토리 (Phone History)

아이폰에서 사용자가 직접 기록하거나 공유한 모바일 활동을 암호화 보존하고, Phone History 서버와 Second Brain 검토 흐름으로 연결하는 모바일 기억 계층입니다.

## 현재 상태

- 버전: `0.1.0-predevice`
- 서버·계약·iOS 구현: 완료
- 재현 가능한 Ubuntu predevice Gate: 구현 완료
- macOS Xcode simulator/device Gate: 구현 완료
- 실제 iPhone 서명·설치·A닷 공유 인수검사: 기기 연결 대기
- 현재 Closure: `READY_FOR_DEVICE_VALIDATION` 또는 Gate 실패 시 `NOT_READY`
- 실기기 Closure: 아직 승인하지 않음

정확한 현재 판정은 `evidence/predevice-gate-result.json`을 기준으로 한다.

## 제공 기능

- 빠른 메모와 작업 시작 기록
- Safari·앱 공유 메뉴의 URL·텍스트·사진·파일 저장
- 사용자 명시형 A닷 통화 녹음 가져오기
- Siri·Spotlight·단축어 App Intents
- App Group + Keychain + AES-GCM 오프라인 큐
- HTTPS Bearer 동기화
- 이벤트별 서버 영수증을 받은 항목만 안전 삭제
- 서버 타임라인, 삭제, 검토 후보
- Second Brain inbox-only handoff over `POST /api/uploads` (vault-path config is a migration error)
- dedup, conflict, tombstone, PII/secret redaction, prompt-injection flag

## 의도적으로 하지 않는 것

- 다른 앱 화면·키 입력·전체 알림 감시
- 카카오톡·A닷 내부 DB 직접 접근
- VPN/DNS 기반 웹 추적
- 자동 통화녹음 우회
- FamilyControls 특별 권한 의존
- 검토 없는 canonical 장기기억 승인

## 구조

```text
contracts/   PhoneEvent JSON Schema, fixture, OpenAPI
server/      암호화 ledger, API, candidate, Second Brain sink
ios/         SwiftUI 앱, Share Extension, App Intents, XCTest
scripts/     계약 생성, predevice, Mac, 실기기 Gate
tests/       Python 서버·보안·API 회귀테스트
docs/        계획, 아키텍처, 보안, 인수검사, 추적표
evidence/    JUnit, 정적검사, Gate 결과
```

## Ubuntu predevice 검증

```bash
cd phone-history
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python scripts/run_predevice_gate.py
```

결과:

- `evidence/predevice-gate-result.json`
- `evidence/pytest-junit.xml`
- `evidence/predevice-static-report.json`
- 단계별 `evidence/*.log`

## 서버 실행

```bash
cd phone-history
.venv/bin/python -m phone_history --help
.venv/bin/python -m phone_history serve --help
```

운영 서버는 공인 HTTP에 직접 노출하지 않는다. loopback에 bind하고 Caddy/Nginx 등 TLS reverse proxy 뒤에 배치한다. API token과 암호화 key는 저장소에 커밋하지 않는다.

Second Brain으로 넘길 때는 `PHONE_HISTORY_SECOND_BRAIN_BASE_URL`만 설정한다. 허용 값은 `https://…` 또는 `http://127.0.0.1:…`이다. 토큰 값은 저장하지 않고 `PHONE_HISTORY_SECOND_BRAIN_TOKEN_ENV`(기본 `SB_WEB_TOKEN`)가 가리키는 환경변수에서 요청 시점에 읽는다. `PHONE_HISTORY_SECOND_BRAIN_VAULT`만 있으면 프로세스는 `ConfigurationError`로 끝나며 볼트 경로로 되돌리지 않는다. 업로드는 `POST /api/uploads`(선언한 SHA-256 포함), 철회는 `POST /api/uploads/retract`이고 `deleted: true` 영수증이 없으면 로컬 사건은 pending으로 남는다.

## Xcode 프로젝트 생성과 시뮬레이터 Gate

Mac에서:

```bash
brew install xcodegen
cd phone-history
scripts/mac_predevice_gate.sh
```

이 스크립트는 계약 생성, privacy Gate, XcodeGen, generic simulator build, XCTest를 실행하고 `evidence/mac-predevice-*`를 만든다.

## iPhone 연결 후

소스 파일을 수정하지 않고 Apple Team ID를 환경변수로 지정한 뒤:

```bash
xcrun devicectl list devices
PHONE_HISTORY_DEVELOPMENT_TEAM=<TEAM-ID> \
PHONE_HISTORY_DEVICE_UDID=<udid> \
scripts/physical_device_gate.sh
```

이후 `docs/DEVICE-VALIDATION-HANDOFF.md`의 D1-D12를 순서대로 검증한다. 자동 build/test가 PASS여도 수동 evidence가 없으면 `DEVICE_CLOSURE=NOT_READY`다.

## 사용 흐름

1. 앱 설정에서 HTTPS 서버 URL, API token, 기본 프로젝트를 저장한다.
2. 직접 메모하거나 다른 앱의 공유 메뉴에서 `폰 히스토리에 저장`을 선택한다.
3. A닷 녹음만 `A닷 통화 녹음=예`로 명시한다.
4. 오프라인이면 AES-GCM queue에 남는다.
5. 앱 열기·수동 동기화·기회형 BGTask에서 서버로 전송한다.
6. 서버가 ID별 성공을 확인한 사건만 로컬 queue에서 제거한다.
7. 후보는 `UNVERIFIED / UNREVIEWED / canonical=false`로 검토함에 들어간다.

## 문서

- `docs/DEVELOPMENT-PLAN.md`
- `docs/ARCHITECTURE.md`
- `docs/SECURITY-PRIVACY.md`
- `docs/DEVICE-VALIDATION-HANDOFF.md`
- `docs/TRACEABILITY.md`
