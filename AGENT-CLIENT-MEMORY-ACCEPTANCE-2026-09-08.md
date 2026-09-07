# 실제 Codex·Claude 공통 기억 인수

상태: **두 종류의 실제 CLI 클라이언트에서 같은 격리 저장소의 양방향 기록·회수 검증 완료. 운영/접근 범위/자동 수집·주입 완료는 아님.** SDK 클라이언트 두 개를 두 앱으로 계산하던 간접 증거를 실제 설치된 클라이언트의 도구 호출로 보강했다.

## 실제 연결과 결과

| 단계 | 실제 클라이언트 | 실제 MCP 동작 | 독립 확인 |
|---|---|---|---|
| A 기록 | Codex CLI 0.153.4 | `sb_remember` 1회 | 정확한 원문 inbox 1개 |
| A 처리 | Second Brain CLI | `ingest`, `compile` | 정상 run, 인용된 committed page 및 봉인 세대 |
| A 회수·B 기록 | Claude Code 2.1.261 | `sb_search` → `sb_read_page` → `sb_remember` | A의 알려주지 않은 코드 회수, B 원문 inbox 1개 |
| B 처리 | Second Brain CLI | `ingest`, `compile` | 정상 run, 인용 page 및 다음 봉인 세대 |
| B 회수 | 새로운 Codex CLI 실행 | `sb_search` → `sb_read_page` | B의 알려주지 않은 코드 회수 |

최종 **MCP 호출 6건 성공, source_item 2개, 원문 CAS bytes 일치**다. 각 읽는 client의 프롬프트에는 검색 표지만 있고 정답 코드는 없다. 양쪽 모두 검색 결과가 선택한 page/record ID와 digest, 같은 generation binding의 원문에서 코드를 회수했고 최종 답변에도 포함했다.

각 client 실행은 현재 로그인된 실제 모델을 사용했다. 반면 서버 compile은 `agent-memory-compiler-fixture.py`라는 명시적 결정적 fixture로 원문에 인용만 붙였다. 실제 LLM 요약·충돌 판단 품질이나 자비스의 승인된 V3 요청 saga를 이 검증으로 주장하지 않는다.

최종 실행 시간은 Codex 기록 14.30초, Claude 조회·기록 13.30초, Codex 회수 19.44초다. 모델·client 시작·MCP 호출을 포함한 각 1회 실행 시간으로, provider 지연 p95가 아니다.

## 검증 도구와 실패 판정

- `scripts/agent-memory-acceptance.py`: 새 격리 vault/config, 서로 다른 무작위 검색 표지와 코드, 실제 세 번의 client 실행, 명시적 CLI 처리, CAS/원장 대조.
- `scripts/agent_memory_events.py`: 모델의 완료 문장이나 프로세스 종료 코드 대신 native client의 도구 호출·결과·최종 turn을 검사한다. Claude tool_use와 tool_result ID를 대응하고, Codex의 실제 MCP status/result를 확인한다.
- 원문과 최종 답변의 코드 일치, search/page의 같은 세대, 선택된 record ID와 digest 일치를 요구한다. 최종 감사기를 보존된 원본 이벤트에도 적용했다.
- 실패 도구인데 CLI 종료가 0인 경우, 누락/중복/잘못 연결된 결과, 다른 세대/record/page, 원문 없는 최종 답변을 통과시키지 않는 회귀 검사를 추가했다.

첫 Codex 실행은 `approval_policy=never`에서 MCP 승인 요구를 처리하지 못했다. 실제 native event는 `status=failed`였는데 프로세스 종료 코드는 0이었다. 원문 저장은 없었고 검증은 실패 처리됐다. 이를 CLI 종료 코드만 확인하는 통합 검사로 놓쳐서는 안 된다.

확인된 Codex의 도구별 설정 `mcp_servers.<id>.tools.<tool>.approval_mode`를 사용해 검증용 server의 선택된 도구에만 `approve`를 명시했다. 전역 설정이나 모든 도구의 권한은 변경하지 않았다. 설정 키는 [공식 Codex 설정 참조](https://developers.openai.com/codex/config-reference)와 설치 버전의 실제 실행으로 확인했다. Claude는 명시적 MCP config와 `--allowedTools`의 세 도구만 사용했다. 위험한 전체 sandbox 우회 플래그는 사용하지 않았다.

중간 성공 실행에는 실험적 skill-discovery 차단 flag의 안내가 있었으므로 최종 설정에서 제거했다. 최종 Codex 이벤트의 해당 경고는 0개다.

## 현재 지원표

| 연결부 | 공통 읽기 | 기록 | 자동 로그 수집 | 자동 문맥 주입 |
|---|---|---|---|---|
| Codex CLI 0.153.4 | schema5 검색·원문·다른 client의 기억 실제 회수 | inbox capture 실제 확인 | 기존 파서 fixture와 별개; 실제 자동 연결 미검증 | 미완료 |
| Claude Code 2.1.261 | schema5 검색·원문·다른 client의 기억 실제 회수 | inbox capture 실제 확인 | 기존 파서 fixture와 별개; 실제 자동 연결 미검증 | 미완료 |
| JARVIS | 기존 adapter/서명 fence·수명주기 인수 유지 | V3/outbox/control 완료 인수 유지 | 실제 task 결과 수집은 원본 차단 전파 보류 유지 | 미완료 |
| Codex/Claude GUI, Cursor, OpenCode/OMO 등 | 이번 실제 실행 대상 아님 | 미검증 | 미검증 | 미검증 |

MCP profile은 `remember-schema5`, 삭제 sequence는 0, 운영 주체는 같은 신뢰된 소유자다. 일반 CLI client는 자비스의 삭제 이후 서명 fence를 자동 발급받는 연결부가 아니다. 따라서 삭제 이후/정정 수명주기·서명 갱신·scope를 포함한 범용 운영 연결 완료로 확대하지 않는다.

## 바로잡은 사용 안내

README의 일반 stdio 도구 목록에 있던 `sb_run` 안내를 수정했다. 실제 기본 stdio는 6개, schema5는 9개 도구다. `sb_run`은 desktop용 서버 표면에만 있다. 일반 stdio의 `sb_remember` 성공은 inbox 접수이며, 명시적 CLI 또는 운영 배치 처리 후 검색해야 한다. 검증 harness도 이 경계를 그대로 통과한다.

## 재현과 증거

저장소 루트에서 다음을 실행한다. 실제 모델 사용량이 발생하며 기존 client 로그인은 필요하다. 운영 자료를 읽거나 운영 MCP 설정을 수정하지 않는다.

```bash
TMPDIR=/var/tmp uv run python scripts/agent-memory-acceptance.py
TMPDIR=/var/tmp uv run pytest -q tests/test_agent_memory_events.py tests/test_mcp_remember_profile.py tests/test_mcp_profile_compatibility.py tests/integration/test_walking_skeleton.py
```

- 최종 실제 인수: `/var/tmp/sb-agent-memory-acceptance-s30wy2r3/evidence.json` 및 각 client `.jsonl` / `.stderr` / 프롬프트. `/var/tmp/sb-agent-memory-final.log`.
- 최종 원본 재감사: 같은 디렉터리 `readback-verification.json`. 상대 client 정답이 reader 프롬프트에 없다는 확인, 실제 page/generation/record/source identity를 기록했다.
- 최초 승인 설정 실패: `/var/tmp/sb-agent-memory-acceptance-wbbfbe7l/evidence.json`. 중간 성공: `/var/tmp/sb-agent-memory-acceptance-bskfnxhm/evidence.json`.
- 관련 회귀 **22 passed / 7.14초**, `/var/tmp/sb-agent-memory-regression-final.log`. 앱 제품 코드는 이번에 바꾸지 않았으므로 이전 전체 638 passed/2 skipped를 이번 새 전체 검사 결과로 재사용하지 않는다.
- 최종 타입 검사 0 errors/0 warnings, Ruff 통과. 타입 표기 정리 후 감사기 회귀 13개를 다시 실행해 통과했다(위 22개와 중복). 최종 감사기 SHA-256 `d7a722b7aec75041f6c6825573142b667e9a4ff24707c4144814092aeed1ae6b`로 보존된 실제 이벤트를 재검증했다.
- 검증한 provider 소스 트리 hash는 `08f60e4b6d609a7a9e78395e3532d525abb9f25a72004f3d59ed47e388ea89e3`, 진입 commit은 `364750c`다. 실제 모델 실행 후 도구 변경은 타입 표기와 native 결과 감사 강화이며 최종 감사기로 저장된 실행 증거를 다시 검증했다.

## 남은 핵심

[접근 범위 구현 전 ADR](SHARED-MEMORY-SCOPE-ADR-2026-09-08.md)에 현재 권한/분류 결손과 source→record→page→export/context 경계를 기록했다. 기존 검색의 active/reference 필터를 프로젝트 권한처럼 사용하는 구현은 보류한다. 범위 claim 발급은 자비스에 두고 Second Brain의 새 승인·권한 엔진은 만들지 않는다.

B4 프로젝트/사용자/agent 범위와 정정 UI, B5 공통 context pack·실제 전달 receipt·compaction 후 재공급, B6 운영 배포/독립 DR, B7 100회 managed 쓰기·한국어 품질 및 B8 검증은 유지한다. 이번에 실제 CLI 두 종류를 검증한 사실이 이 항목들의 완료 증거는 아니다.
