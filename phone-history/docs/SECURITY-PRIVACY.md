# 폰 히스토리 보안·개인정보 설계

## 1. 위협 모델

보호 대상:

- 사용자가 직접 입력한 메모와 프로젝트 정보
- 공유한 URL·텍스트·사진·문서
- A닷 통화 녹음 원본과 전사 후보
- 서버 API 토큰과 로컬 queue key
- 이벤트·첨부의 무결성 및 삭제 상태

가정하는 위협:

- 기기 분실 또는 로컬 백업 유출
- App Group 파일 복사 및 암호문 변조
- 네트워크 중간자 공격
- 동일 이벤트 반복 전송
- 악성 웹페이지·문서·통화 전사 안의 프롬프트 인젝션
- 서버/Second Brain 장애 중 데이터 유실
- 공유 확장 오작동 또는 시간 제한
- 사용자가 A닷이 아닌 파일을 통화 녹음으로 잘못 분류

## 2. 수집 최소화

0.1.0은 다음 권한을 요청하지 않는다.

- 위치
- 마이크
- 사진 라이브러리 전체
- 연락처
- 캘린더
- Bluetooth
- Local Network discovery
- FamilyControls / DeviceActivity
- Network Extension / VPN

수집 진입점은 앱 직접 입력, 공유 확장, 사용자 실행 App Intent뿐이다. 공유 확장은 제공된 `NSItemProvider` 항목만 읽는다.

## 3. 기기 저장

- queue key: 256-bit random, iOS Keychain
- 접근성: `AfterFirstUnlockThisDeviceOnly`
- 앱/확장 공유: 동일 Keychain access group
- 이벤트 암호화: AES-GCM
- AAD: queue format version + event ID
- 저장 단위: 이벤트마다 `.phq` 파일 하나
- 파일 권한: 0600
- 파일 보호: `completeUntilFirstUserAuthentication`
- 손상 파일: 자동 삭제하지 않고 사용자에게 표시

같은 이벤트 ID가 이미 존재하면 기존 암호문을 복호화하고 canonical JSON SHA-256을 비교한다. 같으면 idempotent, 다르면 conflict다.

## 4. 첨부 처리

1. 공유 확장이 provider 임시 URL의 파일 크기를 먼저 확인한다.
2. 10 MiB를 초과하면 읽기 전에 거부한다.
3. 허용 범위 파일은 callback 안에서 완전 복사한다. memory mapping으로 임시 URL 수명을 넘기지 않는다.
4. SHA-256과 byte count를 PhoneEvent 계약에 포함한다.
5. 이벤트 전체를 AES-GCM 큐에 넣는다.
6. 서버가 hash와 size를 다시 검증한다.
7. 서버 첨부 vault는 별도 암호화한다.

A닷 통화 여부는 파일명·앱명으로 추정하지 않는다. 사용자가 Share Extension의 `A닷 통화 녹음`을 `예`로 바꿔야 하며, 비오디오 파일이면 거부한다.

## 5. 전송

- 실기기 서버 URL은 HTTPS만 허용한다.
- HTTP는 `localhost`, `127.0.0.1`, `::1` 개발 루프백만 허용한다.
- URL user/password component를 거부한다.
- Bearer token은 Keychain에만 저장한다.
- 토큰을 query string, 로그, 이벤트 metadata에 넣지 않는다.
- HTTP 오류 본문 전체를 UI나 로그로 재노출하지 않고 짧은 public error code만 사용한다.
- 2xx만으로 queue 원본을 삭제하지 않는다.

## 6. 서버 저장·삭제

- 암호화 SQLite와 첨부 vault 사용
- attachment path traversal 차단
- canonical content SHA 기반 중복 검사
- event ID 재사용 충돌 차단
- 삭제 시 이벤트·첨부 제거 후 tombstone 기록
- tombstone event 재수집 차단
- maintenance 작업은 인증 필요
- `/health` 외 제품 API는 Bearer 인증 필요

## 7. AI 입력 격리

URL, 웹문서, 공유 텍스트, 파일, 전사 결과는 모두 `untrusted_input=true`다.

서버는 다음을 수행한다.

- API key, token, 주민번호, 이메일, 전화번호 등 마스킹
- prompt injection 위험 패턴 표시
- 원본과 후보 요약의 evidence reference 유지
- 외부 명령·URL 자동 실행 금지
- Action Hub 자동 승인 금지
- canonical 자동 승격 금지

## 8. 개인정보 제어

앱에서 제공하는 제어:

- 수집 일시정지
- 기본 프로젝트 변경
- 호스트 단위 URL 제외
- 로컬 대기 이벤트 개별 삭제
- 로컬 대기 큐 전체 삭제
- 서버 타임라인 이벤트 삭제
- 손상 큐 항목의 명시적 삭제
- 후보 검토 요청 또는 제외

`검토 요청`은 canonical 승인과 다르다. 폰 앱에는 canonical 승인 버튼이 없다.

## 9. 보존

- 로컬 큐: 서버가 이벤트별 성공을 확인할 때까지 보존
- 손상 큐: 사용자 삭제 전 보존
- 서버 이벤트: 운영 보존정책 또는 사용자 삭제까지
- raw transient processing: 서버 정책에 따라 최소화
- Second Brain: 원본이 아니라 review candidate와 evidence reference

통화 원본은 일반 텍스트 사건보다 높은 `restricted` 민감도로 표시하고 별도 vault 정책을 적용한다.

## 10. 검증

자동 검증:

- plaintext marker가 `.phq`에 없는지
- AES-GCM bit flip 탐지
- 동일 ID 다른 내용 conflict
- 비HTTPS/URL credentials 거부
- oversized attachment 선제 차단
- app/share entitlement parity
- 민감 권한·감시 API 부재
- Share Extension 직접 네트워크 호출 부재
- canonical=true 자동 설정 부재

실기기 검증:

- 앱과 확장이 실제 provisioning에서 같은 key를 읽는지
- 재부팅 후 첫 unlock 전 보호되는지
- 앱 강제 종료·잠금 후 queue가 남는지
- A닷 실제 공유 provider type을 읽는지
- BGTask가 실패해도 foreground recovery가 되는지
