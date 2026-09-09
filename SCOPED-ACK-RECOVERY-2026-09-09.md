# 수락 응답 유실 복구: 원래 요청의 읽기 조회와 단일 기록

JARVIS 구현 커밋: `d3c1766`.

## 결과

수락 응답을 가지고 있지 않은 자비스 클라이언트가 **원래 쓰기 요청만으로 현재 권한을 검사받아 수락 결과를 회수**하도록 연결했다. 요청을 재전송하거나 수락 시각을 추정하지 않는다. SB 원장에 저장된 원래 수락 결과의 무결성을 검증하고, 그 시각과 파일 해시를 그대로 반환한다.

실제 JARVIS outbox의 이미 전송한 시도를 만들고 `accepted_result_json=NULL`을 확인했다. provider 저장 후 수락 응답을 읽기 클라이언트에 전달하지 않았으며, 자비스는 감독되는 실제 stdio MCP의 `recoverRequestStatus(request)`로 조회했다. 회수된 수락을 원래 attempt에 기록한 직후 별도 프로세스를 exit 73으로 종료했다. 이후 새 프로세스 2개에서 다시 기록해도 **attempt 1 / provider_accepted event 1 / FK 오류 0**이었다. 재claim은 거절됐고 자비스 상태는 reconciling이다.

## 계약과 구현

- 명시적 새 읽기 프로필 `scoped-record-read-v5`. 기존 v1~v4 바이트와 기본 production v2를 유지한다. scoped 쓰기 프로필 v4와는 다른 버전 체계다.
- 도구/인자 형태는 v4와 같고, 상태 응답에서 찾은 요청에만 `acceptance`를 추가한다. `not_found`에는 수락을 만들지 않는다. 새 SHA-256: `4aaadbd6c5670c6f69e811567e2a93abcd746112d86697cfd391ef49aa4853c3`.
- SB `read_scoped_request_status(..., include_acceptance=True)`는 기존 수락 replay 무결성 검사를 재사용한다. 기본 false로 이전 응답을 보존한다. 현재 읽기 scope를 응답 전후 검사하며 원장은 변경하지 않는다.
- JARVIS `recoverRequestStatus(request)`는 v5에서만 사용한다. 원래 요청을 역사 시점에 codec으로 검증·동결하고 provider/owner/projects/policy를 현재 issuer scope와 대조한다. 요청 본문은 읽기 인증이 아니다.
- 회수된 acceptance는 기존 수락 parser로 요청·원본 시각·파일 해시를 대조한다. 완료 proof/receipt도 기존 상태 parser를 재사용한다. 로컬 acceptance를 이미 알고 있다면 회수값이 그 값과 같은지도 검사한다.
- 기존 `recordMemoryScopedOutboxAcceptance`의 원래 fence/attempt 결합·원자 기록·replay 처리를 재사용했다. 새 outbox, 재전송 권한, 승인 소비, 자동 완료 처리는 추가하지 않았다.

## 검증

- 최종 SB 전체: **1,260 passed / 2 skipped / 242.39초**, `/var/tmp/scoped-v5-full.out`, exit 0. 전체 Ruff 및 상태 reader 정적검사 0 errors/0 warnings.
- 최종 J 관련 재검사: 20 passed / 2 files / 0.978초(확대 검사와 중복). 최종 격리 emit/lint 통과, 동일 build로 실제 종료·MCP 복구 재검증 exit 0.
- 초기 SB 상태·MCP 검사: 23 passed / 13.47초. pending/proved 모두 원래 수락 반환, 이전 모드의 필드 부재, 원장 dump 불변, 저장 수락 결과 손상 거절 포함.
- JARVIS 확대: 78 passed / 9 files / 25.53초. 복구 parser, not_found, 잘못된 acceptance/해시, 구 프로필 거절, 고정 transport, issuer/policy, 기존 기억 읽기와 수락 기록 회귀 포함.
- 격리 패키징에서 v1~v5 계약과 checksum이 원본과 일치. 이전 네 프로필 해시 불변.
- 실제 v2/v3/v4는 각각 새 fixture로 읽기·재시작·정책 철회 인수를 통과했다.
- v5 실제 복구: 로컬 acceptance 없이 조회, MCP 재시작 후 일치, provider/issuer 정책 철회 뒤 복구 조회 거절, 원래 JARVIS attempt로 기록, commit 직후 종료·새 프로세스 replay·재전송 없음.

[실제 프로세스 및 호환성 결과](SCOPED-ACK-RECOVERY-2026-09-09.json). 수락 기록 프로세스는 3개이며 첫 종료 코드는 의도한 73이다. 이번에는 SIGKILL이나 운영 장애를 주입한 것이 아니다.

인증 세션·키·시계와 provider의 내부 쓰기 callback은 fixture다. 읽기는 실제 정책/서명 검사와 MCP 프로세스를 거친다. 운영 인증된 scoped 쓰기 전송 완료로 보고하지 않는다. 린트에서 미사용 구조 분해 변수를 발견해 제거했으며, 검사 조건을 완화하지 않았다.

## 남은 과제와 보류

1. **최종 완료:** 회수한 durable proof와 현재 artifact/출처 분류·삭제 fence를 원래 attempt에 묶어 최종 완료를 기록해야 한다. 현재는 accepted/reconciling까지다.
2. **수락 전 또는 최초 활성 세대 이전:** 현재 scoped MCP는 활성 generation pin을 요구한다. 초기 pending/활성 세대 부재의 조회 인수와 복구 정책은 남는다.
3. **공개 쓰기·운영 인수:** 실제 인증 쓰기 전송, native agent 세션에서 저장→다른 agent 회수, 혼합 버전/정정/삭제/복원과 운영 rollout은 계속 남는다. 전체 M1–M14 목표를 유지한다.

`not_found`를 미전송 증거로 해석해 재전송하거나, 해시만으로 자동 settled를 만드는 접근은 보류한다. 이번에는 운영 DB·설정·vault·서비스를 변경하지 않았고 push/배포하지 않았다.
