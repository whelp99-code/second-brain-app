# 범위 제한 기억 응답의 자비스 검증 — 2026-09-09

제품: SB `ec76b14`, JARVIS `8a697d0`. [실측 JSON](SCOPED-RESPONSE-CONSUMER-2026-09-09.json).

서버가 범위를 검사하더라도 소비자가 다른 요청·세션의 응답을 받거나 잘못된 record를 받아들이면 공통 기억 인수를 완료할 수 없다. 이번 변경은 제한 조회·검색 응답을 기존 자비스 record 검증기에 연결하는 내부 소비자 구현이다. 실제 앱의 supervised transport와 인증 세션 연결은 아직 남는다.

## 변경

- SB `sb/mcp.py` 제한 응답에 원 요청 digest와 실제 사용한 claim의 digest를 반환한다. claim 전체의 canonical JSON에 `orca-jarvis/memory-access-claim-binding/v1\0` domain을 붙여 SHA-256을 계산한다. 기존 서명·범위·키·세대·조회 전후 정책 검사를 통과한 후 반환한다.
- JARVIS `src/second-brain-scoped-read.ts`는 caller가 보존한 요청·claim digest 및 만료와 응답을 대조한다. 응답에서 기대값을 복사하지 않는다. 만료된 claim은 fence가 아직 유효해도 거부한다.
- provider·세대 형식·삭제 sequence/root, 요청한 페이지, 허용 결과 개수, 페이지/전체 바이트 예산을 검사한다. 같은 페이지의 서로 다른 content digest가 섞이면 거부한다. 미지 필드·비정상 객체·잘못된 경로도 거부한다.
- 기존 `second-brain-evidence-parser.ts`의 record 검증을 재사용한다. 본문 digest·record ID·출처·민감도·유효 시각을 검증하고 실제 content digest를 source_version으로 사용한다. 가짜 frontmatter를 만들어 기존 페이지 형식을 우회하지 않는다. current/stale/conflict 및 authority=none 의미를 유지한다.
- 응답 digest는 인증 서명이나 데이터 진실성의 독립 증명이 아니다. 신뢰할 수 있는 기존 전송 경로, caller의 최신 권한 검사, 실제 작업 성공 증거가 별도로 필요하다.

## 검증

| 항목 | 결과 |
|---|---|
| JARVIS 새 소비자 및 기존 schema4 회귀 | 17 passed, 2 files, 1.02초 |
| SB claim·제한 MCP·검색·정책 회귀 | 19 passed, 3.28초 |
| SB Ruff 전체 sb/tests | 통과 |
| SB 변경 제품 모듈 basedpyright | 0 errors / 0 warnings |
| JARVIS ESLint, TypeScript 격리 emit | 통과 |
| 실제 CLI→정책 파일→JARVIS issuer→별도 stdio MCP→Node 소비자 | 조회와 검색 각 record 2개, 새 MCP 프로세스에서도 동일 |
| 실제 응답 변조 | 호출별 요청 digest·claim digest·본문 변조 3종 거부 |
| 현재 정책 변경 | 동일 연결에서 키 철회·정책 변경·손상·누락 거부, 설정 복원 후 재개 |

실행: `TMPDIR=/var/tmp uv run python scripts/scoped-mcp-acceptance.py <격리 JARVIS build>`.
원 증거: `/var/tmp/page-access-acceptance-c8_18704/scoped-mcp-result.json`.
4개 소비 결과는 조회·검색을 재시작 전후 반복한 것이며 고유 기억 8개를 의미하지 않는다. 합성 원본, fake compiler, 테스트 authority DB·세션·고정 시각을 사용했다. 실제 파일 정책 resolver와 issuer, 실제 Python stdio, 실제 Node 검증 코드는 실행했다.

이번 변경 뒤 전체 Python 스위트를 재실행하지 않았다. 이전 전체 1,138 passed/2 skipped는 `db685e9` 시점의 기록이다. `uv run pyright` 실행 파일은 없었고 저장소 의존성인 `basedpyright`로 검사했다.

## 호환성·잔여

`scoped-record-read-v1`은 아직 운영 인수 전인 명시적 제한 서버 프로필이다. 두 digest 필드를 필수로 검사하므로 새 소비자는 이전 제한 응답을 거부한다. 기존 frozen schema3/4/5/6/7 계약을 완화하거나 해시를 바꾸지 않았다. 배포 전에 별도의 동결된 scoped transport 계약과 프로필 호환 검증을 연결해야 한다.

실제 앱 세션→resolver→issuer→supervised transport→consumer→context 연결, 최신 정책/삭제 상태의 소비 직전 재확인, scoped 쓰기/status/resolve/export/restore, 세션 보존·삭제와 전체 운영 인수는 남는다. 이번 커밋은 전체 ACL·모든 에이전트 자동 수집·자비스 운영 완료를 뜻하지 않는다.
