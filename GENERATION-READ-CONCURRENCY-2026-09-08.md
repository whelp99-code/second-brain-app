# 갱신 중 공통 기억 조회와 세대 전환

기준일 2026-09-08. I3의 LLM 처리 중 읽기 차단을 수정했다. 작성자 직렬화·reader pin·삭제 원장의 유효성 검사는 유지하고, 실제 자비스 완료 확인과 두 MCP 클라이언트의 조회를 컴파일 진행 중에 검증했다. 운영 배포와 대표 데이터 p95 목표 달성은 별도 인수 항목이다.

## 원인과 변경

기존 `GenerationMutationService.mutate()`는 세대 선택부터 복사·LLM·Git/색인 생성·전환·이전 세대 정리까지 `generation.lock` EX를 보유했다. 모든 reader는 같은 파일의 SH가 필요하므로 느린 컴파일이 자비스의 기본 10초 read deadline을 넘길 수 있었다. 잠금만 바꾼 첫 실제 MCP 검사도 시간초과했다. 조회 진입 시 호출하는 `maintain()`이 다시 writer를 기다렸기 때문이다.

| 단계 | writer mutex | generation.lock | 의미 |
|---|---|---|---|
| 기존 상태 복구·부모 선택 | EX | EX | 이전 전환 정리와 현재 부모/삭제 원장 확인 |
| sealed 부모에서 새 세대 준비 | EX 유지 | SH | 작성자는 하나, 기존 세대 검색·페이지·상태 조회는 동시 실행 |
| 전환 준비·활성화·폐기 | EX 유지 | EX | 진행 중인 reader가 종료된 뒤 parent/high-water 재검사, 전환·이전 세대 폐기 |
| 일반 조회 | 획득 안 함 | SH | 한 응답 전체에서 같은 세대와 등록 reader 수명 유지 |

새 `generation-writer.lock`은 내용 없는 커널 잠금이다. 별도 서버·큐·watcher·승인 체계를 추가하지 않는다. `GenerationStore.exclusive()`도 같은 순서로 mutex를 획득하므로 backup·export·maintenance·직접 activate도 작성자와 직렬화된다. legacy vault의 최초 이전은 SH 준비 모드를 사용하지 않는다. 프로세스 종료 시 커널이 두 잠금을 해제한다.

`flock`의 SH→EX 전환 자체를 원자적이라고 가정하지 않는다. writer mutex를 계속 보유하고 EX 복구 뒤 실제 active parent와 tombstone high-water를 다시 확인한다. 삭제 접수로 원장이 바뀌면 준비 결과는 `TOMBSTONE_SET_STALE`로 활성화를 거부한다. 조회도 실제 pin·fence·active high-water 검사를 거치므로 삭제된 이전 세대를 답으로 제공하지 않는다.

MCP 조회의 물리 유지보수는 `maintain_if_idle()`에서 잠금을 즉시 얻을 수 있을 때 수행한다. busy이면 정리만 미루고 실제 reader pin을 얻는다. 명시 유지보수와 쓰기 경로의 기존 복구는 계속 실행된다. 만료된 export가 정리 전 `available`로 남아 있으면 상태 조회를 `EXPORT_EXPIRED` 오류로 거부한다. 실제 파일 삭제 전 `expired` 완료 상태를 만들어 서명하지 않는다.

## 함께 발견한 최초 세대 초기화 결함

첫 remember 직후 export를 실행하면 `PROVIDER_SURFACE_INVENTORY_INCOMPLETE`가 재현됐다. 실제 inventory에서 필수 `surface:5 / log.md`가 누락돼 있었다. 초기 세대에는 source가 없어 `init_vault()`를 건너뛰던 것이 원인이었다.

초기 세대도 기존 Vault 초기화를 거치게 수정했다. 필수 log와 gitignore가 만들어지며, inventory 검사를 완화하지 않는다. sealing에서도 `raw/`, `.sb/`, `generation.json` 규칙을 항상 마지막에 배치해 상속된 제외 취소 규칙이 원문을 새 Git 이력에 포함하지 못하게 한다. 원문은 private CAS와 generation manifest에 계속 보존한다. 첫 기억→export 성공과 실제 `git ls-files`/`git log -- raw`가 비어 있음을 검사한다. 기존 활성 세대를 직접 수정하거나 과거 운영 Git 객체를 자동 삭제하지 않았다.

## 검증 방법과 범위

`tests/integration/test_generation_concurrency.py`는 별도 프로세스의 실제 pipeline compile을 Pipe 경계에서 멈춘다. 부모가 명시적으로 계속하라고 보내기 전까지 stage가 끝날 수 없으므로, 조회 성공이 실제 동시 실행을 증명한다. 임의 sleep이나 LLM 응답 속도 추측을 사용하지 않는다.

- 실제 stdio MCP의 검색·페이지·generation status가 같은 부모 세대와 실제 record를 반환한다. 10초 제한 안에서 확인한다.
- 두 번째 writer가 첫 successor를 부모로 사용하고 inbox와 기존 기억을 보존한다. reader pin이 살아 있으면 exclusive 전환을 얻을 수 없다.
- 준비 중 writer를 강제 종료한 뒤 기존 기억 조회와 새 writer 실행이 성공한다.
- 준비 중 삭제 원장이 증가하면 무서명 조회와 이전 세대 조회를 거부하고, 준비 결과도 활성화하지 않는다. 이후 실제 삭제 요청을 처리해 proved/sequence 1과 원문 부재를 확인한다.
- export 만료 시 busy 상태 조회는 실패하며 파일이 아직 있다는 사실을 보존한다. idle 유지보수 이후 실제 파일 삭제와 signed expired 상태를 함께 확인한다.

실제 자비스 재현 명령:

```bash
TMPDIR=/var/tmp node scripts/jarvis-memory-acceptance.mjs ../Orca-JARVIS --owner-confirmed --approval-rollback --runtime-cli --record-limit --record-budget --sensitive --after-delete --during-compile
```

합성 owner 승인과 격리 vault/DB를 사용한다. 삭제 이후 민감 record 64개를 저장한 뒤 별도 Python compiler를 준비 단계에서 유지한다. 그동안 자비스 CLI 완료 cycle, 페이지·최근 조회, 별도 MCP 클라이언트 재조회를 실행하고 나서 compiler를 해제한다. 최근 변경 목록이 비어 있어도 `current`가 될 수 있으므로 저장 판정은 64개 전체 record ID 대응에 근거한다.

관측 결과: control completed, outbox settled, 두 클라이언트 current, 민감 record 64개, 추가 dispatch 0, review 원문 잔여 0, cleanup/control 오류 없음. 컴파일 중 완료 확인·조회 구간은 약 1.4초였다. 이 시간에는 여러 호출과 새 MCP 클라이언트 시작이 포함된다. 대표 데이터의 단일 요청 p95로 보고하지 않는다. 외부 LLM 서비스 품질·실제 Codex/Claude 앱의 자동 수집/주입 검증도 아니다.

최종 전체 검사: **564 passed, 2 skipped / 138.84초**. optional embeddings extra 검사는 저장소 기본 명령대로 제외했다. `/var/tmp/sb-generation-concurrency-verified-tests.log`. 실제 자비스 동시 조회 최종 구간은 **1394.48ms**, `/var/tmp/sb-jarvis-concurrent-compile-verified-acceptance.log`.

독립 검토에서 만료된 export 상태와 상속 gitignore의 negation 우선순위를 지적받아 수정하고 각각 회귀 검사를 추가했다. 최종 재검토의 추가 actionable은 없다. 변경 파일 타입 검사는 오류 0/경고 0, 전체 Ruff와 두 Node 하네스 구문 검사가 통과했다. 전체 검사에는 실제 프로세스 동시성·만료 경계 5개와 Git 제외 회귀 2개가 포함되므로 집중 검사 수를 합산하지 않는다.

## 남은 작업과 보류

1. **운영 적용과 부하:** 소스 변경은 운영 release에 반영되지 않았다. activation·대량 폐기·backup/export 구간은 여전히 EX를 사용한다. 대표 데이터에서 p95 2초·timeout 0 목표와 공정성/부하를 측정해야 한다.
2. **강제 종료 잔여물:** writer kill 후 잠금/조회/다음 쓰기는 복구되지만, 다른 mutation ID로 만든 `.staging` 잔여물의 자동 폐기는 기존 B3 과제다. 원장·활성 세대·진행 요청 대응 없이 디렉터리를 일괄 삭제하는 변경은 보류한다. 삭제 완료 증거를 만들 때 기존 inventory 검사는 잔여물을 계속 거부한다.
3. **export 소비:** 자비스의 signed export status 및 expires_at 검증은 아직 없다. 이번 SB 오류는 기존 transport에서 일반 `SECOND_BRAIN_TOOL_ERROR`로 실패 처리되며 성공으로 처리하지 않는다. 세부 코드 전달과 signed status 소비는 I1 후속으로 남긴다. 내보내기 전체 운영 인수 완료로 판정하지 않는다.
4. **후속 공통 기억 기능:** 실제 후보/publication/UI, 실제 앱별 접근·수집·주입, 프로젝트 범위, 일반 LF/V2 정정, 문맥 예산·전달 이력, 한국어 검색 평가를 계속 진행한다.

기존 B0~B8 전체 범위는 [구현 원장](IMPLEMENTATION-STATUS.md), OSS 방향과 기능 대조는 [통합 계획](OSS-ABSORPTION-INTEGRATION-PLAN-2026-09-07.md)을 따른다. frozen MCP/서명 wire 계약과 네 OSS 선택 흡수 방향은 유지한다.
