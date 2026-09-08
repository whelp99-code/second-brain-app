# 세션 시각 결함 수정 및 누적 전체 회귀

2026-09-09, JARVIS `eafe913`. [기계 검증 결과](PHONE-SESSION-CLOCK-2026-09-09.json).

## 결함과 수정

실제 격리 build의 세션 저장소에서 issued_at=1000000에 발급한 쿠키를 checked_at=999999에 인증하자 `ok`가 반환됐다. 신규 회귀에서는 NaN·무한대·음수 발급, 발급 이전 갱신, 마지막 touch 이전 인증까지 7개가 실패했다. 만료 시간과 현재 시각의 차이만 검사하여 역행·비정상 시각이 거부되지 않았다.

발급에는 유효한 비음수 정수 시각과 계산 가능한 만료 시각을 요구한다. 인증/갱신의 만료 판정은 비정상 시각과 lastSeenAt 이전 시각도 거부한다. 인증 중 GC로 무효화한 세션은 시계가 정상화돼도 되살리지 않는다. 기존 idle 경계 및 정상 touch 정책을 유지했다. 시계 역행 때문에 무효화된 쿠키는 새 세션 발급이 필요하다.

## 검증

- 수정 전 신규 회귀 7 failed / 기존 6 passed.
- 수정 후 세션·기억 공급자·게이트웨이·기억 프록시 57 passed / 5 files / 1.14초.
- TypeScript 격리 emit, 변경 파일 ESLint, diff 통과.
- 실제 build 재실행: 발급 이전 인증 invalid, 시각 복구 후 같은 쿠키도 invalid.
- 실제 issuer→phone session source→supervised MCP→scoped client 조회·검색 및 쿠키 누락·응답 직후 정책 철회 거부 재인수 통과. `/var/tmp/page-access-acceptance-3vomzejh/scoped-mcp-result.json`.

실제 인수는 기존 제품 코드를 실행하지만 테스트 owner/key·합성 원본·fake compiler·고정 시각을 사용한다. 운영 HTTP 로그인 인수나 배포를 의미하지 않는다.

## 누적 전체 검사

코드 변경을 멈춘 상태에서 SB `0b969d7` / JARVIS `7ae0684` 시점에 `TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py`를 실행했다. **1,141 passed / 2 skipped / 214.33초**. 원 로그 `/var/tmp/shared-memory-current-full.out`.

이 전체 검사는 위 JARVIS 시각 수정 직전의 누적 상태다. 시각 수정 후에는 관련 57개와 실제 MCP를 검사했다. 서로 다른 범위의 테스트 수를 합산하지 않는다.

## 남은 연결 조건

기존 `MemoryReferenceReader`는 읽기와 전달 전후에 `sb_generation_status`를 요구한다. scoped 프로필은 현재 read/search만 제공하므로 일반 reader의 프로필만 바꾸는 방식은 동작하지 않는다. 범위가 적용된 상태 조회 계약, 소비자 status 검사, 실제 HTTP 인증 세션 전달과 프로젝트 정책 배정이 선행되어야 한다. 공통 CSRF를 agent 인증으로 간주하는 우회는 계속 보류한다.

모델/native 세션의 전달·보존·삭제, scoped 쓰기·resolve·복구 및 M2~M14 전체 완료 조건을 유지한다. 운영 설정·DB·dist·서비스를 변경하거나 푸시/배포하지 않았다.
