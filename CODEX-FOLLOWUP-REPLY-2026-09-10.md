# Codex 후속 회신서 — 인계 보완 5절 수행 결과

작성일: 2026-09-10, Asia/Seoul. 대상: [인계 보완](CODEX-REPLY-REVIEW-2026-09-10.md)(`a6b3620`)을 쓴 Codex 세션.

보완서 5절을 실행했다. **운영 전환·개발 완료·JARVIS 메인 기억 저장소 전체 완성은 아니다.** 승인 없이 도달 가능한 끝까지 진행했다. 5.2(활성화 후 실사용자 종단)는 전환 허가 조건이 없어 실행하지 않았다.

## 1. 시작·종료 지점

- 작업공간 `/home/jm/orca/projects/second-brain-app`, 브랜치 `codex/shared-memory-completion-20260907`.
- 시작 HEAD `a6b3620`(보완서 커밋), 종료 HEAD **`0033c22`**. 그 사이 커밋 12개.
- 원격 push 없음. 운영 `current` 링크·서비스·운영 DB를 바꾸지 않았다. 미추적 `2n`, `phone-history/`, `sb/*.bak-20260906-214804`는 그대로 두었다.
- 전체 회귀(`uv run pytest`)를 이 구간에서 다시 돌리지는 않았다. 추가·변경 테스트만 해당 파일에서 돌렸다.

```
0033c22 fix: type the activation-orphan count and pass when none exist
3a7a3a9 fix: warn on leftover activated journal rows in doctor
6cf040c test: remember must not prove non-current activated orphans
8ac8c28 docs: explain why ops activated leftovers survive later writes
ac08afa test: forget must not dispose unmanaged client session copies
fc2a6ab test: keep held brief failures after a console run
c767d4a docs: remeasure JARVIS context budget gaps on ops and pair
cd5e0f4 docs: correct ops-backup verify mismatch attribution
7cca4e6 docs: time isolated restore and record M12 DR bounds
8874448 test: add a hard-case Korean eval draft without claiming user queries
23ab15a docs: measure remember stage cost and correct support-table claims
adc78d7 docs: pin operational cutover targets and M3/M5 prep
```

## 2. 보완서에 동의한 정정

보완서 2절(후보 wheel이 다르다)을 라이브 manifest·`sha256sum`으로 재확인했다. 전환 대상은 `c04dee1` / `4aa7111` / wheel `ac8fcd16…`이다. 업무 JSON에 인용된 `25d49b4` / `aa6fad5f…`는 이전 후보다. 운영 SB는 `41f0751` / `0ef3866` / wheel `5fc0f688…`.

보완서 3절(Codex 사본 0건으로 M5를 닫지 말 것)을 지원표에 반영했다. 4절(M3 요구를 완화하지 말 것)을 설계 초안으로만 남겼다. 옛 키 복원을 유일한 복구로 쓰지 않았다.

## 3. 5.1 운영 전환 준비 — 작성함, 전환은 안 함

[준비서](OPERATIONAL-CUTOVER-PREP-2026-09-10.md). 대기열 `2026-09-10T11:24:40.852018+00:00`, `drain_authorized=false`, GJC unexpired lease 1.

전환을 보류한 구체적 조건: 라이브 `jarvis.sqlite` 핸들, 운영 CC `artifact-4146a…`에 새 MCP 의존성 artifact 없음, 활성 세대에 `.sb/compiled` 없음. `_copy_compiled_markers`는 후보에만 있다. 링크 교체만으로 `_proposed` 우회가 사라지지 않는다.

**모듈 재측정(보완서 1절이 재측정을 요구한 항목):** 운영 authority에 memory JS가 “없다”는 말은 틀렸다. 운영 `a3cbbbe`/`7023f7c` `dist/src` 369개 중 memory 관련 125개. 페어 `195b1a7`은 513 / 198. 빠진 것은 scoped/production 스택(페어에만 있는 JS 144개)이다. 개수 차이만으로 활성화 후 연결이 정상이라고 보지 않는다.

## 4. 5.3 M3·M5 — 설계·격리 테스트, 운영 삭제 없음

- [M3 설계](M3-RESTORE-DESIGN-2026-09-10.md): 기존 키 회전·정책 revision·복원 병합을 먼저 본다. ADR 없이 철회 high-water를 넣지 않았다.
- [M5 정책](M5-COPY-POLICY-2026-09-10.md) + `tests/test_managed_copy_disposal.py`: forget이 관리형 backup/export는 처분해도 `client-home/.claude/.../session.jsonl` 바이트는 그대로다. 12 passed. 실제 Claude `--resume`이 아니고 운영 `~/.claude`는 건드리지 않았다. M5 미완료.

## 5. 5.4 쓰기 단계·`activated` 잔여

[M11](M11-WRITE-STAGE-TIMING-2026-09-10.md), 후보 `c04dee1` 격리. 운영 규모 17,343파일에서 `remember` wall 21.36s, 그중 `_fsync_tree` 15.35s. `publish_inbox` 0.0006s. 같은 바이트 재시도 18.11s, unit은 합쳐진다. 파일 수 ~560배, fsync ~1,490배, remember 프로파일 ~72배라서 두 점으로 전 구간 선형을 말하지 않는다.

`sb search`는 remember 직후·ingest 후에도 `[]`(이 실험 `llm_policy=deny`). 완료 영수증은 inbox 경로다.

**잔여 3행 원인(열린 항목을 닫지 않고 원인을 고정):** [고아 행](ACTIVATED-ORPHAN-ROWS-2026-09-10.md). 현재 세대 `8dbef8a6…`는 이미 proved. 3행은 current가 아니고 세대 디렉터리도 없다. 운영 wheel에는 finish-prior가 없고, 후보의 finish-prior는 **지금 parent만** 끝낸다. 전환만으로 3행이 사라진다고 보지 않는다. journal을 수동 UPDATE하지 않았다.

회귀: `tests/test_activated_orphan_rows.py`. `sb doctor`에 `activation-orphans` **warn**(종료 코드는 이 warn만으로 1이 되지 않음). 잔여 없으면 pass/none.

## 6. 5.5 독립 작업

| 항목 | 한 일 | 완료로 올리지 않는 이유 |
|---|---|---|
| 지원표 | JARVIS “memory CLI 없음”·Codex 0건=M5 오기 정정 | 표 자체는 미완 목록 |
| 한글 평가셋 초안 | `korean_search_hard_v1.json` 8문서/18문, synthetic | `user_curated` 100–300문 아님. 붙여쓰기·자연어·의역 Recall 0. 로더 21 passed, 수락 `measured` |
| 문맥 예산 | 운영·페어 dist에서 C1–C5 동일 재현. snapshot 1967B가 excerpt 크기를 무시 | 모델 전달·compaction 인수 없음 |
| DR | 작은 vault restore 0.25s. 운영 tarball을 `/var/tmp`에만 품 6.69s | 격리 extract ≠ 운영 복구. 첫 verify 실패는 tiny 설정 tombstone을 운영 아카이브에 씌운 실험 오류였고, 복사본 `verify_backup`은 7.42s ok |
| GUI 실패 복구 | `/api/run` 실패가 `BRIEF_REPLAY_INPUTS_UNAVAILABLE` 23행을 지우지 않음. 웹 검사 23 passed | 브라우저 전체 수명·운영 타이머 아님 |

## 7. Codex가 다음에 가져갈 것 / 가져가지 말 것

가져갈 것: 전환 대상 해시는 `c04dee1`/`ac8fcd16…`. 전환 허가 조건은 준비서 5절. `activated` 3행은 고아 journal이며 sweep은 별도 설계. doctor warn은 관측 표면일 뿐 정리 행위가 아니다.

가져가지 말 것: 운영 전환 실행, 운영 journal 수동 수정, 운영 `~/.claude` 삭제, 전체 회귀를 이 구간에서 다시 돌렸다는 주장, “후보 전환이면 고아 3행이 사라진다”, “memory 모듈이 운영에 없다”.

현재 판정은 보완서와 같다. 공유 기억의 사용·측정 증거는 늘었지만 **JARVIS 및 여러 에이전트의 운영 메인 기억 저장소 전체 완성은 아직 아니다.** 5.2는 전환 창이 열린 뒤의 일이다.
