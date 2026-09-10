# 인증 연결 시험의 문서 날짜와 조회 시각 일치

## 확인한 원인

최신 workspace 인증 시험의 HTTP 503은 시험 시각 불일치로 재현됐다. `page-access-acceptance.py`가 실제 CLI로 문서를 컴파일할 때 `Vault.write_pages`는 실제 UTC 날짜를 `updated`에 기록했다. 반면 하위 서명·MCP·자비스 소비자의 시험 시각은 2026-09-09T00:00:00Z로 고정돼 있었다. UTC 9월 10일에 생성한 문서는 이 소비자에게 미래의 기억이 된다. SB의 기존 `memory_records._validity`는 `updated`를 유효 시작 시각으로 사용하고, 자비스는 해당 범위를 벗어난 record를 stale로 분류한다.

격리 진단용 Node preload로 reference reader의 두 단계 결과 종류만 관측했다. generation_status는 data였고 search는 stale였다. 자비스 reference reader는 current/no_data 이외 결과를 `MEMORY_REFERENCE_PROVIDER_UNAVAILABLE`로 거부하며 HTTP가 `PHONE_UPSTREAM_UNAVAILABLE` 503으로 매핑한다. 운영 provider 장애나 Codex quota 실패가 이 503의 원인이었다고 볼 근거는 없다. 진단 파일은 /var/tmp에만 만들었고 자비스 빌드·소스는 수정하지 않았다.

## 변경

시험의 실제 CLI compile 호출을 Python bootstrap으로 실행하고 해당 프로세스의 `sb.vault.datetime`만 기존 서명 시험 시각으로 고정했다. 실제 ingest/compile/봉인·원장 결합·MCP·자비스 처리 코드는 계속 실행한다. 기록 유효기간, stale 거절, 서명, 정책 검사는 변경하지 않았다. 커밋된 Git blob의 updated가 2026-09-09인지 assertion으로 검사하고 결과 JSON에도 page_clock을 기록한다.

## 검증

모델 호출을 끈 전체 scoped acceptance는 exit0이다. 결과 `/var/tmp/page-access-acceptance-d1yl2bmq/scoped-mcp-result.json`, 실행 로그 `/var/tmp/sb-scoped-clock-fixed-20260910.log`.

- HTTP 문맥 record 2개, 서로 독립된 stdio 클라이언트 2개에서 각 record 2개 회수.
- 에이전트 정책으로 새 세션 2개 연결, 독립 에이전트 동일 record, 제한된 peer record 0개와 원래 에이전트 record 2개 유지.
- cookie/CSRF/미부여 세션/정책 철회 거절, 세션 만료 후401, 철회 후403.
- v1/v2 소비자 계약, 응답 변조 거절, 제출 중복/독립 프로세스 재전송 거절, 종료 중 철회 검사 통과.

이 첫 통과 실행 후 커밋 본문의 날짜 assertion과 page_clock 보고 필드를 추가했다. 이후 실제 모델 포함 재시험 결과는 아래 후속 기록으로 구분한다. Ruff와 diff 검사는 통과했다. 실제 사용자 신원·업무가 아닌 격리 fixture이며 운영 전환·전체 M1–M14 완료를 의미하지 않는다.

날짜 assertion을 포함한 실제 두 제품 시험은 HTTP 초기 조회와 Claude 검증을 지나 Codex 실행에서 exit1로 종료했다. `/var/tmp/sb-native-clock-fixed-20260910.log`의 Codex JSONL은 `turn.started`→`error`→`turn.failed`, 사유는 `You've hit your usage limit`이며 MCP 도구 실행은 없다. 날짜 수정 전의 HTTP503과 다른 실패다. 두 제품 전체 성공으로 집계하지 않으며 다른 계정·모델로 우회하지 않았다.

최종 Claude 단독 전체 재시험 **exit0**: 실제 Claude Code **2.1.261** MCP 호출1회, 독립 stdio SDK 클라이언트2개 각 record2개, HTTPS3회, 이후 철회·만료·중복 등 전체 assertions 통과. `/var/tmp/page-access-acceptance-uqhnxzo6/scoped-mcp-result.json`, 로그 `/var/tmp/sb-claude-clock-fixed-20260910.log`. Codex 호출0회인 단독 결과와 앞선 Codex 실패를 구분한다. 날짜 assertion 및 page_clock 기록을 포함한 최종 소스로 실행했다.

실패 fixture와 수정 fixture의 실제 페이지를 추가로 읽어 각각 `updated: '2026-09-10'`, `updated: '2026-09-09'`임을 확인했다. 운영 시각이나 운영 기억을 변경한 것이 아니다. 전체 pytest 재실행/설치물 재빌드는 이번 변경 범위에 포함하지 않았다.
