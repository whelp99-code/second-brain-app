# 폰 히스토리 개발계획서

- 제품명: 폰 히스토리 (Phone History)
- 프로젝트 ID: `phone-history`
- 기준 버전: `0.1.0-predevice`
- 작성 기준일: 2026-09-04
- 상태: 구현 완료 / 실기기 검증 대기

## 1. 목표

아이폰에서 사용자가 직접 기록하거나 공유한 링크·텍스트·사진·파일·A닷 통화 녹음을 시간순 사건으로 보존하고, 서버에서 중복 제거·에피소드·검토 후보를 만든 뒤 기존 Second Brain inbox로 전달한다.

폰 히스토리는 다른 앱의 화면, 키보드 입력, 전체 알림을 감시하는 제품이 아니다. iOS가 공식적으로 제공하는 공유 확장, App Intents, 앱 내부 입력, 기회형 BackgroundTasks만 사용한다.

## 2. 제품 경계

### 2.1 0.1.0 포함

- SwiftUI 아이폰 앱
- Share Extension
- 빠른 메모 및 작업 시작 기록
- Siri·Spotlight·단축어용 App Intents
- A닷 통화 녹음의 사용자 명시형 가져오기
- App Group 기반 AES-GCM 오프라인 큐
- HTTPS Bearer 인증 동기화
- 이벤트별 서버 영수증 기반 안전 삭제
- 서버 타임라인과 검토 후보 조회
- 서버 이벤트 삭제 및 tombstone
- Second Brain inbox-only handoff
- 개인정보·삭제·제외 호스트 설정
- 서버·계약·iOS 정적 Gate와 실기기 Gate 스크립트

### 2.2 0.1.0 제외

- 다른 앱의 전역 화면/클릭/키 입력 기록
- 전체 알림 수집
- VPN·DNS 기반 웹 추적
- 카카오톡·A닷 내부 DB 직접 접근
- 자동 통화 녹음 우회
- FamilyControls/DeviceActivity 특별 entitlement
- 위치·마이크·사진 라이브러리 전체 권한
- 검토 없는 자동 canonical 승격
- 기록 안의 명령문/URL 자동 실행

## 3. 핵심 데이터

- `PhoneEvent`: 개별 모바일 사건. 서버 fixture와 JSON Schema가 계약의 단일 원천이다.
- `PhoneEpisode`: 시간·프로젝트·출처가 가까운 이벤트 묶음.
- `PhoneMemoryCandidate`: `UNVERIFIED`, `UNREVIEWED`, `canonical=false`로 시작하는 검토 후보.
- 첨부 원본: SHA-256 검증 후 서버 암호화 vault에 저장한다.
- Second Brain: 원장 자체가 아니라 검토 가능한 inbox handoff 대상이다.

## 4. 구현 단계와 완료 상태

| 단계 | 구현 범위 | 상태 | 증거 |
|---|---|---:|---|
| P0 | 제품 정의·iOS 제약·위협 모델 | 완료 | `ARCHITECTURE.md`, `SECURITY-PRIVACY.md` |
| P1 | PhoneEvent·OpenAPI·fixture 계약 | 완료 | `contracts/`, 생성 스크립트 |
| P2 | 암호화 SQLite·첨부 vault·dedup·tombstone | 완료 | `server/`, Python 회귀테스트 |
| P3 | Second Brain inbox-only sink | 완료 | sink 테스트, 직접 wiki/daily 쓰기 금지 |
| P4 | iOS Core·Keychain·App Group AES-GCM 큐 | 완료 | `ios/Core/`, XCTest |
| P5 | SwiftUI 앱·타임라인·검토함·설정 | 완료 | `ios/App/` |
| P6 | Share Extension·A닷 명시형 가져오기 | 완료 | `ios/ShareExtension/` |
| P7 | App Intents·BGTask 보조 동기화 | 완료 | `AppIntents.swift`, `BackgroundTasks.swift` |
| P8 | Ubuntu predevice Gate·Mac/Device Gate 자동화 | 완료 | `scripts/`, `evidence/` |
| D1 | Xcode simulator build/test | 기기 호스트 대기 | `mac_predevice_gate.sh` |
| D2 | Apple 서명·App Group·Keychain 실기기 검증 | 아이폰 연결 대기 | `physical_device_gate.sh` |
| D3 | Safari/Files/Photos/A닷 수동 인수검사 | 아이폰 연결 대기 | `DEVICE-VALIDATION-HANDOFF.md` |

## 5. 안전 설계 결정

1. 공유 확장은 네트워크 요청을 하지 않고 암호화 큐에만 기록한다.
2. 큐는 이벤트별 AES-GCM 봉투이며 이벤트 ID를 AAD로 묶는다.
3. 동일 ID·동일 해시는 idempotent, 동일 ID·다른 해시는 conflict다.
4. 서버 HTTP 2xx만으로 로컬 원본을 지우지 않는다. 이벤트별 성공 ID를 받은 항목만 삭제한다.
5. 응답에 영수증이 없으면 원본을 보존하고 재전송한다.
6. 서버·JARVIS·Second Brain 장애가 모바일 수집을 막지 않는다.
7. A닷 파일은 파일명으로 자동 추정하지 않고 사용자가 토글로 선언한다.
8. 검토함은 canonical 승인 기능을 제공하지 않는다.
9. 앱·공유 확장은 같은 App Group/Keychain group을 사용하되 최소 entitlement만 갖는다.
10. 서버 경로와 이벤트 필드는 OpenAPI·Schema·fixture에서 Swift로 생성한다.

## 6. 0.1.0 완료 기준

### 자동 Gate

- 서버 테스트 전체 통과
- Python lint·format·compile 통과
- 계약·OpenAPI Swift 생성 통과
- 개인정보 plist/entitlement 정적검사 통과
- Swift 구문 parse 또는 Xcode build 통과
- App Group/Keychain 설정 parity 통과
- 공유 확장 네트워크 직접 전송 0건
- canonical 자동 승인 코드 0건
- git whitespace 검사 통과

### 실기기 Gate

- 서명된 앱과 Share Extension 설치
- 앱/확장 사이 Keychain·AES-GCM 큐 공유
- 오프라인 기록 후 복구 동기화
- 동일 이벤트 재전송 시 서버 1건 유지
- Safari 링크·텍스트·사진·일반 파일 저장
- A닷 오디오 저장 및 비오디오 오분류 차단
- 재부팅 전 첫 잠금해제 보호
- 앱 백그라운드/강제종료 후 큐 보존
- 서버 삭제 후 재수집 tombstone 차단
- Second Brain 후보가 미검증·미승인·비canonical 상태 유지

## 7. 후속 버전

- 0.2.0: Safari Web Extension, 프로젝트별 모바일 사용 문맥, Mac Computer History 통합 타임라인
- 0.3.0: 에피소드 기반 작업 복원, 반복 모바일 업무 탐지, 검토용 자동화 Draft
- 1.0.0: JARVIS 운영 브리핑·Side Notch 이어하기·복구/보존정책 관리

특별 entitlement 기능은 0.1.0 완료 조건이 아니며 별도 실험 트랙으로만 진행한다.
