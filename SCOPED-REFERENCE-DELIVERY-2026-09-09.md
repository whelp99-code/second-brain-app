# 제한 기억과 기존 문맥 공급기 연결 — 2026-09-09

JARVIS `6a9d1d8`, SB 인수 `fa0cc11`. [실측 JSON](SCOPED-REFERENCE-DELIVERY-2026-09-09.json).

## 구현

`createScopedMemoryReference`가 기존 `MemoryReferenceReader`에 scoped v2 검색/상태 결과를 연결한다. reader가 실제로 사용하는 search 의존성만 받도록 타입을 좁혔으며 지원하지 않는 recentChanges/conflicts 함수를 가짜로 채우지 않았다. 기존 개인정보·삭제 억제·세대 일치·record 근거·분량·준비 시각·제출 직전 검사와 단일 제출 규칙은 유지한다.

scoped 클라이언트에 현재 status issuer로 검증한 접근 식별값을 얻는 내부 연결 기능을 추가했다. reference factory는 첫 provider/principal/agent/session/projects/policy/key/삭제 이력 식별값에 묶인다. 검색/상태 전후 및 reader의 최종 transaction/제출 검사에서 현재 식별값과 비교한다. 세션이나 정책이 바뀌면 새 reader를 만들어야 하며 과거 준비물을 새 범위로 전달하지 않는다.

검증된 current/stale/conflict/no_data 의미를 기존 reader 결과로 매핑한다. 상태의 healthy 응답은 scoped 소비자 검증을 통과한 결과만 사용한다. stale/conflict를 current로 바꾸거나 원문 없는 결과에 근거를 만들지 않는다.

## 검증

- 기존 reference read/submit/deliveries/context 및 새 scoped 연결: **85 passed / 5 files / 38.02초**.
- 새 연결에서 빈 문맥, 동일 payload 1회 콜백, 중복 제출 거부, 준비 후 세션 변경 시 콜백 실행 전 거부를 확인했다. 기존 privacy/세대/만료/키 변경과 제출 중 실패 회귀도 통과했다.
- TypeScript 격리 emit·변경 TS ESLint·diff 통과.
- 실제 격리 CLI→세션 인증→파일 정책→issuer→supervised MCP→scoped client→기존 reader에서 **record 2개 / payload 4,412 bytes**를 준비하고 같은 바이트를 제출 콜백에 전달했다. 중복 제출과 준비 후 쿠키 제거는 콜백 실행 없이 거부됐다.
- 실제 v1/v2 조회, 전후 상태 일치, 응답 직후 정책 철회와 기존 변조 거부도 같은 인수에서 통과했다.

원 결과: `/var/tmp/page-access-acceptance-zq89noh0/scoped-mcp-result.json`.
첫 실제 인수 입력은 max_record_bytes=8192로 기존 4096 상한을 초과해 `MEMORY_REFERENCE_INPUT_INVALID`로 거부됐다. 인수 입력을 4096으로 수정했으며 제품 예산 제한을 완화하지 않았다.

## 인수 한계·후속

실제 provider record와 기존 제품 경로를 사용했으나 owner/key·clock·원본은 격리 fixture이고 compiler는 fake다. 콜백이 받았다는 것은 실제 모델/native 세션이 수신·보존했다는 증거가 아니다. 이번에 `submitInSession`의 실제 native 세션 관측·로그/compaction/삭제 수명까지 연결하지 않았다.

CLI/HTTP 제품 진입점의 실제 인증된 scope 생성, 게이트웨이→백엔드 세션 전달, 프로젝트 정책 배정이 남는다. factory 연결만으로 일반 owner CLI의 프로필을 자동 전환하지 않는다. 만료/철회 단조성, scoped 쓰기/resolve/복구 및 M2~M14 전체 운영 조건을 유지한다. 이번 변경 후 전체 SB 스위트를 다시 실행하지 않았고 기존 1,141 passed/2 skipped 기록의 범위를 확대하지 않는다.
