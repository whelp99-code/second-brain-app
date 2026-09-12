# Grok 최종 제출 — §7 진입점

CODEX-NIGHT-REVIEW-c0b4fce. **운영 전환 없음. 인증 복사 없음. 실사용자 삭제 없음. push 없음. 제품 인수 아님.** Ready는 Codex 검증 인계일 뿐 인수 완료가 아니다.

정본: [GROK-INTEGRATED-COMPLETION-HANDOFF-2026-09-11.md](GROK-INTEGRATED-COMPLETION-HANDOFF-2026-09-11.md) 7절, [CURSOR-HANDOFF-2026-09-10.md](CURSOR-HANDOFF-2026-09-10.md) §7 M1–M14.

## 1. 정확한 버전

| | |
|---|---|
| SB frozen source | `e13cd3b699695fa08fbde521f7a7866c9dfef6a0` |
| 후보 | `/var/tmp/sb-candidate-e13cd3b/releases/d9c6825b9a94cf6637ba01416562e4eb777db7a2` |
| wheel | `1847b5994392cde8f76e21604a26ed2aee3bb4a43bd7eb04e783615465b317fb` (inbox discard 안전경계 포함; a4b228f와 동일하지 않음) |
| JARVIS | `1672626c5f2b0b06f7fb93c900cf8771536b58cd` `/var/tmp/jarvis-artifact-1672626/source/dist` |
| inventory | `e9751dfaf955bab6a1ea15792733e0af576f7bac540ca5efeb0b69d9bccbf9cd` (34768) |
| 운영 current | `41f0751` |
| production_activated | false |
| 소스 커밋 | `84e2c43` — ordinary Alpha→Omega compile MCP latest/exclude. 게이트는 f7c1945 동일 wheel |
| git archive | `scripts/seed-scoped-v4.py` 포함 |
| dispatch | 미변경 (V1-C–F / N1 보존) |

이 패키지는 **Codex 독립 검증 인계**다. 제품 인수/운영 전환이 아니다. 로컬 커밋은 승인된 구현 범위. 구핀 `12db06e`/`a4b228f` 게이트를 이번 소스 검증으로 재사용하지 않는다.

## 2. 요구별 상태 (원 의미)

상태 값만 `verified` / `implemented_unverified` / `blocked_external` / `not_implemented`. 전환 허가가 없다고 전부 `blocked_external`로 두지 않는다. 운영 로그인·실사용자 원문·실제품 자동주입처럼 **정확한 외부 입력**이 필요한 항목만 그렇게 표시한다.

### A–F (통합 인계 원 의미)

| ID | 원 요구 | 상태 | 근거 | 남은 실행 가능 격리 작업 / 정확한 외부 입력 |
|---|---|---|---|---|
| A | 원본·사용자 편집·정정 보존. staging HEAD가 아닌 마지막 컴파일 근거. `USER_EDIT_KEEP_THIS` 보존 + 무수정 페이지 정정 | implemented_unverified | 이전 핀 managed compile / USER_EDIT_KEEP_THIS. 이번 라운드 미재실행 | 격리: 직접 Vault API·`run_compile`·별도 CLI 중단 재시작 조합 재확인. 운영 원본 세트는 소유자 목록 입력 |
| B | 철회 정본·권한·복원. 철회 키 거부, 새 키 fresh claim, 다른 principal/project/session 거부. 구버전 41f0751에 store 없음 | implemented_unverified | 격리 2 클라이언트 철회/회복. 운영 키 복사 금지 | 격리: 후보가 만든 세대·원장·철회 상태 왕복. 운영 키/설정 복원은 허가된 키 자료 없이 불가 |
| C | 하나의 검색 계약·품질·실제 본문 전달. 공통 정규화. assembler→모델 payload 본문/출처/버전/예산 | implemented_unverified | Unicode compact. `gjc.dispatch` V1-C–F (UTF-8 예산, 계보, 동일본문 별도 evidence). dispatch 미변경 | 한글 gold 100–300은 M10. 세션 compaction 이벤트는 M9 |
| D | 실제 공유 기억 수명. 조회→검증→candidate→proved→다른 세션 회수. 실패가 성공으로 승격되지 않음 | implemented_unverified | 격리 schema4 proved + 독립 세션 회수 | 실사용자 1건 원문 계보는 입력. native 사본 처분은 M5/M8 |
| E | 가용성·복구·GUI. MCP p50/p95, DR archive→원장→조회/거부/high-water→새 쓰기, GUI 실패→복구 | implemented_unverified | 아래 M11/M12/M13 | 격리 GUI 전체 수명은 M13. 운영 corpus는 M11 외부 |
| F | 배포 재료와 운영 절차. 새 후보, JARVIS artifact, 3게이트, 런북(명령·서비스·경로·writer 배제≠큐0·설정/백업 hash) | implemented_unverified | frozen 3게이트 EXIT 0. 런북 핀 변수. 전환 미실행 | 이번 harness 커밋+`prepare-release` 후에야 새 후보. 전환은 허가 후에만 |

### M1–M14 (CURSOR-HANDOFF §7 원 의미)

| ID | 원 요구 | 상태 | 근거 | 남은 실행 가능 격리 작업 / 정확한 외부 입력 |
|---|---|---|---|---|
| M1 | 기존 인증 세션·범위 resolver·issuer·gateway를 **실제 운영 진입점**에 연결. 허용 읽기/쓰기, 다른 프로젝트 거부, 종료/철회 정리. drain이 아님 | implemented_unverified | 격리 `createProductionMemoryAccessClaim` + scoped MCP | 운영 진입점 연결은 실로그인 세션(제품/principal/policy 파일). 그 입력 없이 운영 종단 불가 |
| M2 | 실제 사용자 업무 1건: 자비스 조회→검증 결과→저장 요청→영수증→다른 에이전트 새 세션 회수. 완료 1회·재전송 중복 0. 철회 경로가 아님 | implemented_unverified | 격리 schema4 `memreq:scoped:v4:96509d71…` proved, recover-a/b 동일 digest | 실사용자 task/request/candidate 원문은 입력 |
| M3 | 정책 revision/기발급 claim/백업 rollback 전체 수명. 철회·열린 연결·과거 설정 복구 후 과거 권한으로 읽지 못함 | implemented_unverified | 세션 철회 후 `MEMORY_ACCESS_SCOPE_UNAVAILABLE`, 정책 복구 후 재개. 만료 fence `TOMBSTONE_FENCE_REQUIRED` | 운영 과거 config/백업 키 복원은 허가된 자료 없이 불가 |
| M4 | 원작업→검증 결과→기억 원문 계보. 실패·미확정·철회가 성공 경험으로 승격되지 않음. dispatch 본문 계보 하나가 전부가 아님 | implemented_unverified | ExtraLost 잊힘 후 generic reader 0. schema4 본문만 scoped 회수 | 실사용자 원작업 계보는 입력 |
| M5 | native session/compaction/log/WAL/백업 사본의 정정·삭제 수명. 재개·요약·복원·재색인에서 삭제 부활 없음 | blocked_external | SB WAL/SHM 세트 restore는 M12 격리 증거 | 제품/버전별 native 세션·compaction 로그 경로가 필요. 빈 홈 미지원과 다름 |
| M6 | 운영 writer/lease 배제와 단일 작성자 전환·복구. 큐 0과 작성자 배제 구분. 전환 복구가 아님을 drain으로 바꾸지 않음 | implemented_unverified | `writer_busy=true` vs pending 0. restore dest exclusive/COPYFILE_EXCL | 운영 서비스 전환은 허가 없음. 격리 구버전 호환/안전거부는 런북 명령으로 준비 |
| M7 | **모든 지원 읽기 표면**의 범위 일관성. 제목/snippet/score/원문/벡터/관계에서 불허 정보 노출 0 | implemented_unverified | scoped-v3 허용/거부. CLI v4 journal EXIT0. owner wiki 본문 vs project:b deny (`test_unscoped_owner_read_does_not_leak_through_scoped_deny`). web `/api/search`+`/api/pages` owner Cited vs scoped project:b `[]` (`test_web_search_owner_surface_does_not_replace_scoped_deny` 1 passed). generic reader 별도 | **남은 격리:** 운영 원문 세트 입력. vector/hybrid는 scoped_search hybrid=False (`test_scoped_search_disables_hybrid_and_omits_scores`). 관계 필드는 scoped 결과에 없음 |
| M8 | 실제 사용 클라이언트별 수집·조회·쓰기·자동 주입. 제품/버전별 새 세션 상호 회수 | blocked_external | 격리 MCP 세션만 | Codex/Claude/Orca 각 버전·프로필·자동주입 경로 명시 입력 |
| M9 | 자비스 실제 세션 문맥 예산·중복 주입·compaction. 만료·철회 후 재사용 없음 | implemented_unverified | `gjc.dispatch` 예산/세대 재검증 (제품 경로). 세션 compaction 이벤트 없음 | native/Orca compaction 트리거 이벤트. 그 입력이 오기 전 dispatch 경로와 분리 |
| M10 | 실제 한글 사용자 질문 100–300과 정답 근거 | blocked_external | 고정 synthetic/KeepBeta만 | 사용자 큐레이션 정답집 |
| M11 | 큰 corpus 실제 MCP 및 동시 조회/정정·갱신. p50/p95·RSS | implemented_unverified | 정상 Alpha→Omega: `test_normal_correction_and_reader_during_compile`. ingest 세대는 during read 전 변경·Alpha record 유지. Omega 준비중 reader 완료→게시. pinned-read 중 publish는 미검증 | 운영 corpus·강한 동시 게시는 미검증. 보류 분기는 검사특정불가 |
| M12 | 원장/원본 journal 소실 DR와 RPO/RTO. 신뢰 근거 복구·삭제 high-water·재유입 차단·시간 | implemented_unverified | harness-36: 필수 restore+만료 fence 후 schema4 write, recover-a/b/retry, final_fresh `첫 결정`. generic ExtraLost 0 KeepBeta 0. cold restore cap0 1 passed (원 전체회귀 실패1은 별도) | 운영 RPO/RTO는 운영 백업 |
| M13 | GUI 정정/삭제·원문/영수증·실패 복구·운영 timer | implemented_unverified | Chrome CDP `isolated-browser-m13-lifetime.py` EXIT 0: remember fail/success, search/원문, conflict fail/resolve, inbox 영수증 삭제, 검색 유지. Codex actual-ui remember/conflict 버튼 보존. 운영 timer/실사용자삭제는 외부 |
| M14 | 관계 검색 추가 가치 측정 후 제한 채택. 운영 전환이 아님 | not_implemented | hybrid 무근거 후보 증가 | 고정 질문에서 비용 대비 효과·정정/삭제 일관성 입증 전 기본 활성화 보류 |

## 3. 테스트 증거

| 무엇 | 명령/경로 | 결과 |
|---|---|---|
| c0b4fce 두 scoped 세션 | `TMPDIR=/var/tmp node scripts/jarvis-restore-acceptance.mjs /var/tmp/jarvis-artifact-1672626/source/dist` | `/var/tmp/jarvis-crash-restore-36.log` **EXIT 0** (재현은 고정 dist; 당시 실행은 workspace dist와 바이트 동일 범위) |
| 기계 JSON | `/var/tmp/sb-jarvis-restore-qku1N6/result.json` | generic_reader `{extra_lost:0,keep_beta:0}`, `classified_write_after_required_restores:true`, `second_restore_records:1` == final_fresh |
| recover-a | agent `agent:recover-a` session `session:recover-a` | allowed_pages 1, withdrawal_denied, digest `sha256:f3b73d4e44a9205673892efe803c304be08ff27ba713eef85ba847f5104261f6` |
| recover-b | agent `agent:recover-b` session `session:recover-b` | 동일 digest, 다른 agent/session. **recoveredPeer ≠ recoveredScoped 복사** |
| recover-retry | agent `agent:recover-retry` | 동일 digest |
| schema4 write | `scripts/seed-scoped-v4.py` → `accept_scoped_request` + `RequestExecutor` schema4 `source_access` | `memreq:scoped:v4:96509d7156ed7d9f614d92e22eea1ca5e701dae32c99006347aff11965b4a532` proved, page `wiki/memory-725c050a86a52a7ccfa65bd7a19025882e5851de95a428647107f214ebecb4d0`, needle `첫 결정`. ledger 수동 INSERT 없음 |
| 만료 fence | restore-probe restore + past fence | `TOMBSTONE_FENCE_REQUIRED` (harness 기대 실패) |
| 종료 후 권한 | `qku1N6/recovery.env` AUTHORITY_ROOT 생존 | fence seq 3 |
| 설치 3게이트 | `/var/tmp/sb-gates-f7c1945.log` (실행 핀 `f7c1945`, 현재 아카이브 `8edb9d4`와 wheel 바이트 동일. 새 실행으로 바꾸지 않음) | maintenance/integration/`--work` |
| cold restore | `pytest tests/test_cold_restore_write.py` | 1 passed (briefing cap 0). 원 전체회귀 1 failed는 별도 기록 |
| Codex 실제 UI | `/var/tmp/codex-night-e68d5e5-1wan26x9/actual-ui-result.json` | remember400→201, conflict400→200. 재실행 없음 |
| 전체 pytest | 이번 미반복 | Codex 1837 passed / 1 failed / 2 skipped를 이번 집중 수정으로 전체 통과라 바꾸지 않음 |
| fixture vs native vs operational | 이 harness는 **격리 fixture** | 운영/native 인증 종단 아님 |

## 4. 핵심 수명 증거 (M12 이번 계약)

순서: runtime backup → ExtraLost apply → JARVIS 유실 → extra restore → **high-water seq3** → generic ExtraLost 0 KeepBeta 0 → **필수 SB restore + 만료 fence 거부** → **그 다음** schema4 classified write → recover-a/b/retry → final_fresh `첫 결정`. 복원 전 카운터를 최종 성공으로 재사용하지 않음.

| 측정 | 값 |
|---|---|
| fixture | `/var/tmp/sb-jarvis-restore-qku1N6` |
| jarvis_owned_high_water | 3 |
| rto_restore_to_readable_ms | 1958 |
| failure_to_work_available_ms | 9418 |
| jarvis_crash_to_reopen_ms | 46 |
| first-restore concurrent clients | 2 |
| independent_revocations (KeepBeta) | 2 |
| writer_lease.writer_busy | true |

일반 reference reader 결과를 recoveredScoped에 복사하지 않음.

## 5. 재현

```bash
cd /home/jm/orca/projects/second-brain-app
TMPDIR=/var/tmp node scripts/jarvis-restore-acceptance.mjs /var/tmp/jarvis-artifact-1672626/source/dist
# 기대: EXIT 0, classified_write_after_required_restores true
#       recovered_scoped.agent != recovered_peer.agent, digest 동일
#       recovered_retry는 세 번째 조회이며 원장 retry가 아님
#       generic_reader.extra_lost==0, final_fresh 첫 결정
```

종료 후 (ROOT는 런마다 다름):

```bash
set -a; . "$ROOT/recovery.env"; set +a
node scripts/issue-restore-fence.mjs
python scripts/restore-probe.py restore "$ROOT" < "$FENCE"
```

운영 app root 기본값 사용 금지. 운영 키/auth 복사 금지.

## 6. 운영 상태

- 전환 없음. `production_activated=false`. current `41f0751`.
- 실신원 종단 없음.
- 보류: M5/M8 제품별 native 경로, M10 정답집, M1 운영 로그인, 전환 허가.
- recovered-retry = 세 번째 scoped 조회. 원장 retry와 구분.
- M13 기존 HTTP 진입점: remember 400/201+inbox 영수증, pages 원문, conflict 400/200 정정, retention GET(삭제 컨트롤 없음), search 재조회. Chrome 버튼 수명은 Codex actual-ui만 인용.
- M11 정상: `test_normal_correction_and_reader_during_compile` Alpha 본문/record_id → Omega 본문/다른 record_id/새 generation, Alpha 검색 []. reader는 writer 준비 후 완료, 그 다음 게시.
- 보류/미검증(검사특정불가): 보안 경계·삭제 경합·콘텐츠제한 연관 분기. 성공이나 운영입력 대기가 아님. 원 미완료를 외부만으로 지우지 않음.
- 미전환을 운영 완료로 표현하지 않음.
