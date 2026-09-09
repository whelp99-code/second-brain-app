# Scoped MCP read v4: 현재 권한으로 요청 완료 조회

JARVIS 구현 커밋: `34e9588`.

## 결과와 범위

세컨드브레인의 내부 상태 reader를 실제 MCP에 연결하고 자비스 클라이언트의 `requestStatus(request, acceptance)`로 조회하도록 구현했다. 명시적 `scoped-record-read-v4`에서만 새 인자 형태의 `sb_request_status`를 노출한다. **이것은 읽기 프로필 v4이며 scoped 쓰기의 공개 전송 완료를 뜻하지 않는다.**

실제 자비스 production 구성 함수→감독되는 stdio MCP→현재 정책/서명 claim 검사→원장 상태 조회→소비자 proof/receipt 검증을 통과했다. MCP 재시작 후 같은 완료 결과를 조회했고, provider 정책 변경과 issuer 정책 철회 시 거절했다. 시험은 임시 DB·실제 프로세스·fixture 인증 세션/키/고정 시계로 수행했다. 운영 서비스의 인증·배포 인수는 아니다.

## 변경 계약

- 새 고정 계약 `contracts/second-brain-scoped-read-v4.json`, 양쪽 리포 같은 바이트. SHA-256 `707ea8dcbdc2aebe0aaa5c90743ebb247adde9d469dd51a0564c2cb8728d53e2`.
- 기존 v1/v2/v3 해시와 기본 v2 production 설정 유지. 새 프로필의 도구는 `sb_generation_status`, `sb_read_page`, `sb_request_status`, `sb_search`다. 쓰기 도구는 없다.
- `sb_request_status` 인자는 `request`, `read_fence`, `access_claim`. 기존 전역 `request_id` 단독 인자 형태는 새 프로필에서 거절한다. 원래 요청 전체가 method와 함께 access request digest에 결합된다.
- 요청 상태는 응답의 `request_status` 아래 배치한다. 외부 `request_digest`는 현재 조회 claim의 digest이고 내부 것은 원래 쓰기 요청 digest이므로 충돌하지 않는다.
- purpose/operation은 `memory_status/status`. 현재 정책·공개키·서명·프로젝트 범위를 확인하고, generation pin과 삭제 high-water를 유지하며 응답 전 다시 검사한다.
- 자비스 정책 schema v3의 명시적 `sb_request_status` grant만 새 상태 조회를 허용한다. 기존 schema v1/v2나 다른 method grant로 자동 허용하지 않는다. 해당 grant만으로 쓰기 권한은 생기지 않는다.

## 코드와 소비자 검증

SB `sb/mcp.py`에서 기존 `read_scoped_request_status`를 호출한다. 원장에는 maintenance-only 모드로 접근한다. 기존 페이지 read v3의 출처별 접근 분류도 새 프로필에서 유지한다.

JARVIS는 issuer/정책, transport 고정 계약 및 패키징, 응답 envelope 검사, production/client 프로필을 함께 확장했다. `second-brain-scoped-request-status.ts`는 원래 수락/request/provider/scope와 현재 응답을 대조하고, 완료 proof의 실제 본문 해시·generation/head/tree·receipt/status 해시를 확인한다. 증명은 분리된 frozen 객체다. 검증 뒤에도 현재 권한을 다시 검사한다. 외부 요청 snapshot은 codec의 frozen 값으로 유지한다.

응답의 현재 generation과 proof의 과거 generation을 무조건 같다고 검사하지 않는다. 과거 저장 완료와 현재 artifact의 유효성을 별도 확인해야 한다. 이번 변경은 자동 settled/control completed를 수행하지 않는다.

## 이번 검증

- 최종 SB 전체: **1,255 passed / 2 skipped / 223.60초**, `/var/tmp/scoped-v4-full.out`, exit 0. 전체 Ruff 통과.
- 최종 소비자 관련 재검사: 37 passed / 3 files / 18.61초(위 확대 검사와 중복).
- SB MCP 프로필 v1~v4 고정 인자/도구·범위 검사 및 새 상태 조회: 9 passed / 8.31초.
- JARVIS 확대 검사: 72 passed / 8 files / 22.59초. 상태/transport/policy/issuer/기존 scoped client/production/기억 artifact/읽기 검증 포함.
- TypeScript 마지막 타입 검사에서 상태 전용 응답의 `pages` 반환형이 기존 페이지 응답 union과 맞지 않는 오류를 발견했다. 상태 응답이 빈 pages를 명시하도록 수정했고 격리 emit exit 0을 확인했다. 변경 파일 ESLint 통과.
- 격리 패키징에서 v1~v4 계약·checksum 복사 일치. 기존 v1 `2c0bc8a…`, v2 `a5af3004…`, v3 `c3d4b1d…` 불변.
- 최종 실제 stdio 프로세스 인수는 v2/v3/v4를 각각 새 fixture로 실행해 모두 exit 0. v2는 기존 content 관찰, v3/v4는 정확한 artifact 분류 관찰을 유지한다. v4는 완료 상태 재시작 후 일치와 양측 정책 철회 거절도 확인했다.

[실제 프로세스 결과 모음](SCOPED-STATUS-MCP-V4-2026-09-09.json). 초기 개발 중 범용 문자열 확장의 문법 오류는 컴파일 전 점검으로 수정했고, 새 소비자 타입 오류를 수정했다. 기존 계약 검사나 승인 조건을 완화하지 않았다.

## 남은 완료 조건과 보류

1. **수락 응답 유실 복구:** provider 상태 endpoint는 원래 요청으로 조회하지만 현재 자비스 편의 API는 이미 확보한 acceptance를 요구한다. acceptance까지 유실된 원래 attempt에서 수락 결과를 안전하게 회수하는 경로는 추가로 연결해야 한다.
2. **최종 완료 처리:** 현재 권한으로 얻은 durable 상태, 원래 attempt, 현재 artifact/분류·삭제 검사를 결합해 완료를 원자적으로 기록해야 한다. 해시만 맞는 외부 응답으로 자동 완료 처리하는 접근은 보류한다.
3. **첫 활성 세대 이전:** 현재 scoped MCP 경로는 generation pin을 사용한다. 최초 저장 전/활성 세대가 없는 상태에서의 pending 조회는 별도 설계·인수가 남는다.
4. **공개 쓰기와 운영 인수:** scoped 쓰기 인증 전송, 실제 agent A 저장→B 새 세션 회수, 혼합 버전/정정·삭제·복원·운영 rollout은 계속 남는다. 전체 M1–M14 범위는 유지한다.

이번 작업은 push·배포·서비스 재시작·운영 DB/설정 변경을 수행하지 않았다. 인계의 세컨드브레인 정본과 네 OSS 장점 선별 흡수 방향을 유지한다.
