# 실제 업무 한 건의 에이전트 간 기억 공유 — 운영 경로

인계서 8-C의 실제 업무 인수를 운영 진입점에서 실행했다. 합성 fixture가 아니라 **오늘 실제로 수행한 개발 검증 결과**를 업무로 삼았고, **실제 제품 두 개**가 각자의 새 세션에서 같은 기억을 회수했다. 원본 결과는 [증거 JSON](REAL-WORK-SHARED-MEMORY-2026-09-10.json)에 있다.

## 1. 사용한 실제 경로

| 요소 | 값 |
|---|---|
| 에이전트용 MCP 진입점 | `/home/jm/.local/bin/second-brain-agent-mcp` → `app/current/bin/sb mcp`, `SB_CONFIG=~/.config/second-brain/config.toml` |
| 운영 활성 릴리스 | `41f0751aca8906d612961e704bc60dd0855fdabd` (이번 작업에서 전환하지 않음) |
| 등록 상태 | Claude Code 2.1.261 `claude mcp list` connected, Codex CLI 0.154.0 `codex mcp list` enabled |
| 단일 작성자 수집 | `jm-second-brain-refresh.service` — 시간별 운영 타이머가 쓰는 것과 같은 단위 |

## 2. 업무와 검증된 결과

업무는 "HEAD `d4cbdda`의 전체 회귀와 릴리스 후보 `25d49b4` paired 인수"다. 저장 전에 결과를 먼저 검증했다: pytest 1,785 passed / 2 skipped / 569.06초 exit 0, ruff·basedpyright 통과, `check-release-integration`·`check-release-maintenance` 각각 exit 0. 근거 문서는 [회귀](CONTINUATION-FULL-REGRESSION-2026-09-10.md)·[설치 후보](CONTINUATION-INSTALLED-PAIR-2026-09-10.md)이고 커밋은 `1c203ed`다. **실패하거나 미확정인 결과를 성공 경험으로 저장하지 않았다.**

## 3. 계보

1. **저장** — Claude Code 세션 `b78bbcda-60ab-43ad-8e79-77db513d27f9`이 `mcp__second-brain__sb_remember`를 1회 호출해 영수증 `{"inbox_path":"inbox/2026-09-10T031904232122-…-인수.md"}`를 받았다. 디스크의 원문은 684바이트, SHA-256 `8d98629a024cdba18221c4e4fb88b54f3a2f2954831a291b715c9f16bcd971c7`.
2. **수집** — `systemctl --user start jm-second-brain-refresh.service` 결과 success/exit 0, 49.08초. 실행 `f997ea6c…`, `c0898f00…`(compile), `f44fc544…` 모두 pages=1·errors=0.
3. **원장** — `source_item(inbox, source_version 1789010462090458520:684:8d98629a…)`, `unit ed22ceff… span=0-480 normalizer v2`, `derivation compile 7e0da3ad… → wiki/inbox-…-df9d6669.md (done, attempts 1)`, `derivation brief 392ee46e… → daily/2026-09-10.md (done, attempts 1)`.
4. **세대** — 새 봉인 세대 `sbgen:v1:0d8e8501…`(parent `sbgen:v1:c7b034c3…`), vault head `a3e1c50f…`, 커밋 `a3e1c50 sealed generation`.
5. **회수** — 두 제품이 각각 **새 세션**에서 같은 record를 회수했다.

| 제품 | 세션 | 회수 결과 |
|---|---|---|
| Claude Code 2.1.261 | `a7089fa6-a53b-46ff-98b8-d96b29a176eb` | page_id `daily/2026-09-10`, 후보 `25d49b4367945c8fa01ea71f2d83932d8da934d8`, wheel `aa6fad5f…86dcf`, 출처 origin/hash 일치 |
| Codex CLI 0.154.0 (gpt-6-astra) | `/var/tmp/codex-recall2.log` | 동일한 page_id·후보 ID·wheel SHA-256·출처 origin/hash |

저장한 세션과 회수한 세션은 서로 다른 세션이며, 회수 값은 저장 원문의 hash와 같은 출처를 인용한다.

## 4. 음성 대조

같은 운영 MCP에서 Claude 세션 `97361b62-…`으로 두 가지를 확인했다.

- 근거 없는 질의 `zzq내부에없는키워드20260910` → `{"results":[]}`. 없는 사실을 만들어내지 않았다.
- `sb_read_page(id="../../../etc/passwd")` → `page_id escapes vault: ../../../etc/passwd` 거부.

## 5. 실제 사용에서 드러난 결함

운영 릴리스 `41f0751a`가 컴파일한 wiki 페이지에는 같은 sid의 각주 정의가 두 줄 남는다(`[^8d98629a]: …, span=0-480`와 span 없는 중복). 같은 입력의 daily 페이지는 정상이다. 이 중복은 현재 HEAD와 후보 `25d49b4`의 `sb/vault.py` span-우선 각주 dedup으로 이미 수정돼 있다. 즉 **운영 릴리스가 후보보다 오래되어 이미 고친 결함이 실제 사용자 기억에 남는다.** 운영 전환의 근거 항목으로 남기고, 이번에는 `current`를 바꾸지 않았다.

## 6. Codex 클라이언트 관측

- `codex exec`는 기본 approval policy에서 MCP 호출을 `MCP tool call requires approval, but approval policy is never`로 거부한다. `--approve-for-me`(사용 시 `-s/--sandbox`와 함께 쓸 수 없음)로 실행해야 도구가 실제로 실행된다.
- 실행 로그에 `codex_login … refresh_token_invalidated` 오류가 반복 출력되지만 `codex login status`는 로그인 상태를 보고했고, 이번 회수는 정상 완료됐다. 즉 이 오류는 이번 실패 원인이 아니다. 과거 인계의 "Codex 사용량 제한" 관측과 구분한다.

## 7. 아직 남은 것

- **JARVIS 업무 계보**: 운영 authority 릴리스 `a3cbbbe`에는 `memory classify/stage-dispatch/outbox` CLI가 없다(해당 명령은 `195b1a7` 빌드에만 있음). 작업→검증 결과→candidate→영수증의 실제 JARVIS 계보는 운영 authority 전환 뒤에만 가능하며, 그 전환은 인계서 9절의 보류 대상이다. 이번 인수는 그 앞단(사용자 업무 → 기억 저장 → 다른 에이전트 회수)까지다.
- **불허 프로젝트 거부**: 운영 agent MCP는 범위 claim이 없는 표면이라 이번에는 vault 이탈 거부만 확인했다. 프로젝트 범위 거부 증거는 후보 paired 인수의 철회/만료 시나리오에 있다.
- **정정·삭제 수명**: 운영 tombstone high-water를 영구히 올리는 변경이라 사용자 승인 전까지 수행하지 않았다. 격리 후보에서의 삭제·복원 증거와 구분한다.
- 이번 회수는 검색·원문 읽기 경로다. 각 제품의 자동 수집·자동 문맥 주입·compaction 이후 삭제 수명은 여전히 미완이다.
