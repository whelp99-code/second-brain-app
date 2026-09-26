# P04 — iPhone 입력부터 반영 증거

명세 등록 / 구현·실기기 시험 NOT_RUN. Refs #3. 선행 P01 #5, P02 #6. R1 / REQ-01·REQ-09 / Capture+Client+QA / 5–8인일 추정. 기준: 개발계획 5.1·5.2·7.7·15 Gate C. 문서 버전/hash는 #3.

## 목표
기존 Phone History의 공유/App Intent/client/sink 경로를 재사용하여 실제 iPhone에서 보낸 항목이 원본·receipt·사건·검색·Obsidian까지 추적되도록 한다. `device_closure=NOT_RUN` 표시 변경만으로 성공을 만들지 않는다.

## 구현 체크리스트
- [ ] P00에서 현재 iOS 빌드/서명/설치/기기 버전/서버 접근을 확인한다. 현재 프로젝트의 두 client 경로가 있다면 실제 사용 경로를 먼저 확정한다.
- [ ] 공유 메모·웹링크·선택 사진·녹음에 안정적인 device event ID, occurred/observed 시각, MIME, sensitivity, source identity를 붙인다.
- [ ] 전송 전 로컬 영속 보관과 중단 후 재개를 구현한다. 네트워크 응답을 잃어도 같은 멱등키로 재조회한다.
- [ ] 서버 receipt를 수신한 뒤에만 접수 상태를 바꾸며 accepted/processed/searchable/projected/error를 화면에 구분한다.
- [ ] 기존 inbox-only 경계를 유지하고 명시적 pipeline run/scheduler와 연결한다. 승인·canonicalization 플래그를 일괄 true로 바꾸지 않는다.
- [ ] TLS 검증, 기기별 최소 권한, 만료·철회·재로그인 처리를 연결한다. 관리자 장기 토큰을 로그/공유파일에 기록하지 않는다.
- [ ] 음성 원본 저장과 전사 결과를 분리하고 전사 실패/미실행 상태를 보인다. P10 정책 없는 외부 전사를 금지한다.
- [ ] 원문 참조와 정정 요청을 연결하고 동일 항목의 서버 revision/View generation을 사용자에게 확인 가능하게 한다.

## 실제 종단 시나리오
1. 실제 iPhone에서 링크와 메모 각 1건을 공유한다.
2. receipt→raw reference→event revision→검색 결과를 동일 ID 계보로 대조한다.
3. P05/P06 완성 후 타임라인·Obsidian에서 항목과 원문을 연다.
4. 사용자가 내용을 정정하고 P02 경로를 거쳐 5개 surface에서 새 개정을 확인한다.
5. 비행기 모드/앱 종료/서버 재시작/응답 유실/만료 세션을 재현한 뒤 중복·유실 없이 복구한다.

## 예상 코드/인터페이스
`phone-history/ios/`, `phone-history/server/phone_history/service.py`, `sink.py`와 기존 상태 API를 대조한다. 앱/서버 계약 fixture를 함께 갱신한다. 신규 Life API는 P01/P02 계약에 맞춘다. 현 PR의 diff는 이 명세 1개뿐이다.

## 인수조건
AC-01/16: 동일 입력 재전송과 중단 후 영속 수락 자료 유실0. AC-09: 정정→5개 surface 일치. AC-06 연계: 실제 Mac/iPhone Obsidian 링크와 원문 조회. 권한 만료/철회는 R1 기기 계정 경계에서 시험하며 AC-22의 GPS/건강 전체 인수는 P12/P13로 남긴다. P04의 서버 수집 성공만으로 P06 포함 R1 전체 완료라고 하지 않는다.

## 범위 제외·복구
전역 화면/키입력/통화·메시지 DB 무단 수집, 위치·건강 자동 opt-in, 새 모바일 앱 전면 재개발은 제외한다. 수집 OFF는 새 입력만 중단하며 이미 접수된 자료와 삭제/정정 의도는 보존한다. 운영 인증/배포는 별도 허용 범위 내에서 수행한다.

## 완료 증거
기기 모델·OS·앱 build, 서버 revision, redacted receipt/event/View ID, 시나리오 화면, 정상·실패·재개 로그, 단위/통합/실기기 결과를 구분한다. 현재 제품 구현 NOT_STARTED, 모든 시험 NOT_RUN.
