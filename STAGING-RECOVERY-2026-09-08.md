# 중단된 준비 세대의 원본 사본 정리

최신 병합 상태: [100회 쓰기 최종 통과](WRITE-CYCLE-ACCEPTANCE-2026-09-08.md) 후 원 작업공간 `0fecf0a`에 반영했다. 아래 병합 대기 표시는 당시의 검증 이력이다.

## 문제와 수정

실제 대규모 배치의 의도적 프로세스 종료 후 `/var/tmp/sb-write-cycles-dn1i9yhv/share/vault-generations/.staging/f263fc026c67a02c0cec7300dd41262c8dba2be7dea4c14611028826df00872d`에 raw/원장 사본이 남았다. 다음 다른 ID의 배치가 성공해도 이 경로는 제거되지 않았다. 이 이전 실패 증거는 보존했으며 이번 검증은 새 합성 저장소에서 수행했다.

기존 `GenerationStore.build`는 동일 request ID의 준비 경로만 재사용 전에 지웠다. 실행마다 ID가 바뀌는 CLI 경로에서는 중단된 다른 ID의 사본이 계속 남는다. 이 결함은 디스크 증가와 삭제 수명주기에서 처리되지 않은 원본 사본을 남길 수 있으므로 B3/I5의 후속 수정으로 처리한다. 특정 삭제 요청의 완료 proof를 이 관측만으로 무효라고 단정하지 않으며 전체 삭제/복원 인수와 구분한다.

새 `sb/generation_cleanup.py`를 기존 generation writer mutex와 배타 잠금 아래의 유지보수/쓰기 진입점에 연결했다. 새 큐·watcher·별도 원장·승인 경로는 추가하지 않는다. 구현 전 결정은 [ADR](STAGING-RECOVERY-ADR-2026-09-08.md)다.

## 동작과 보호 경계

1. 활성 포인터/기존 저장소 상태를 확인한 뒤 `.staging`만 검사한다. 공개된 세대·active inbox·요청 spool·백업은 정리 대상이 아니다. 비봉인 사본에서 새 사실을 복구하거나 접수 완료를 추정하지 않는다.
2. 전체 준비 경로 목록을 먼저 검증한다. 이름은 기존 64자리 소문자 request hash, 내용은 같은 소유자/장치의 디렉터리와 단일 링크 일반 파일이어야 한다. 잘못된 형제 경로가 있으면 유효한 다른 사본도 지우기 전에 실패한다.
3. 디렉터리를 `O_NOFOLLOW`로 열고 descriptor 기준으로 탐색/삭제한다. inode를 다시 대조하고 부모 디렉터리만 쓰기 가능하게 한다. 외부 파일의 권한을 변경하거나 링크를 따라 삭제하지 않는다. 삭제 후 디렉터리를 fsync한다.
4. 기존 `/proc` descriptor 확인을 재사용한다. 열린 사본은 `GENERATION_STAGING_IN_USE`, 위험한 경로는 `GENERATION_STAGING_UNSAFE`로 실패한다. 실패를 무시해 완료로 보고하지 않는다. 이 descriptor 확인은 기존 Linux 운영 경계이며 물리 매체의 안전 삭제를 뜻하지 않는다.
5. 살아 있는 writer는 준비 중에도 writer mutex를 유지한다. reader의 비차단 유지보수는 바쁜 writer를 기다리거나 그 사본을 제거하지 않는다. 실제 프로세스 종료로 잠금이 해제된 후 정리한다.
6. 중간 삭제 실패는 다음 잠금 진입에서 남은 파일부터 재처리한다. 이미 정리한 사본은 재실행 시 0개다. `sb maintain --once` JSON에 `disposed_staging` 개수를 추가했다. 실제 쓰기 시작 시에도 같은 정리를 수행한다.

## 실제 CLI/MCP 인수

동일 도구를 수정 전/후 provider root에 각각 실행했다. 운영 저장소·서비스·설정은 변경하지 않았다.

| 항목 | 수정 전 | 수정 후 최종 |
|---|---|---|
| 기억 접수·수집·컴파일 | 실제 CLI | 실제 CLI |
| 준비 중 종료 | 실제 자식 프로세스 `os._exit(91)` | 동일 |
| 남은 준비 사본 / raw 파일 | 1 / 1 | 정리 전 1 / 1 |
| 종료 직후 active 파일 hash | 이전과 일치 | 이전과 일치 |
| `maintain --once` 후 준비 사본 | 1 | 0, `disposed_staging=1` |
| 유지보수 재실행 | 실패 기준선에서 종료 | `disposed_staging=0` |
| 후속 새 기억 접수·수집·컴파일 | 이 실패 기준선의 범위 밖 | 완료 |
| 원래 기억과 새 기억의 MCP 회수 | 이 실패 기준선의 범위 밖 | 두 기억 모두 검색/읽기 완료 |
| CAS 원문 | 최초 CLI 원본 | 두 원문 byte 일치, source_item=2 |

최종 MCP는 두 기억 각각의 search/read 7개 generation binding과 record ID/digest·본문을 대조한다. 두 입력은 합성 자료이고 compile은 결정적 fixture다. 실제 모델 요약 품질·자동 문맥 주입·운영 재시작·전체 DR 인수는 아니다.

- 수정 전 증거: `/var/tmp/sb-staging-recovery-e03j9g7f/evidence.json`, `commands.jsonl`; `/var/tmp/sb-staging-before.log`. CLI 유지보수 자체는 exit 0이지만 준비 사본이 남아 인수 도구가 exit 1로 실패 처리했다.
- 수정 후 최종: `/var/tmp/sb-staging-recovery-xztif3vm/evidence.json`, `commands.jsonl`, `mcp.jsonl`; `/var/tmp/sb-staging-after-final.log`. `state=passed`, exit 0, active 불변·raw 일치·새 쓰기/회수·준비 사본 0.
- 제품 hash(리포 기준 상대 경로): `81cd19ad83f8c4564d5cdeb60eec8e3f57d68c42806e9b2a824cc704eff57255`. 실행 중 제품 hash 불변을 검사했다. native 증거 파일 hash는 evidence에 있다.
- 초기 수정 후 실행 `/var/tmp/sb-staging-recovery-g0j1dz76`도 복구됐으며 최종 보고는 원문 byte 검증을 추가한 마지막 실행을 기준으로 한다.

## 자동 검사

- 표준 전체 **733 passed / 2 skipped (211.41초)**. `/var/tmp/sb-staging-full-tests.log`. 검색 수정과 이번 복구 수정이 함께 들어간 격리 제품에 대한 결과다. 원 작업공간의 기존 버전 100회 쓰기 결과와 구분한다.
- 관련 generation 회귀 **25 passed (18.76초)**. 실제 process exit와 다른 request ID의 복구, readonly 디렉터리, 위험한 형제 경로의 삭제 전 거부, 열린 descriptor, 살아 있는 writer, 활성 포인터 오류, 중간 실패 재시도를 포함한다.
- 접수된 pending inbox의 보존 검사를 추가 보강한 최종 복구 모듈 **11 passed (9.92초)**. 위 25개에 포함되는 검사이며 합산하지 않는다. 전체 suite 실행 중 테스트의 보존 assertion을 보강했으므로 해당 최종 assertion은 이 집중 실행으로 별도 확인했다. 제품 코드는 전체 suite 실행 중 고정했다.
- 변경 제품/도구/테스트 basedpyright **0 errors / 0 warnings**, Ruff `sb tests` 및 인수 도구 통과. 로그 `/var/tmp/sb-staging-types-final.log`, `sb-staging-preservation-types.log`, `sb-staging-ruff-final.log`, `sb-staging-focused.log`, `sb-staging-input-preservation-final.log`.

```bash
TMPDIR=/var/tmp python scripts/staging-recovery-acceptance.py
TMPDIR=/var/tmp python scripts/staging-recovery-acceptance.py --provider-root /absolute/path/to/provider
```

## 병합과 후속 범위

원 작업공간의 100회 쓰기 인수는 여전히 이전 제품 hash에서 진행한다. 이 수정은 검색 수정 다음의 `/var/tmp/sb-korean-query-work`에서 구현/검증하며 해당 인수가 끝날 때까지 원 작업공간에 병합하지 않는다. 기존 대규모 실패 증거를 지우거나 운영 cleanup을 실행하지 않았다.

이 검증은 미봉인 준비 사본의 정리다. 정상 봉인됐으나 활성화되지 않은 세대, 외부 사본/백업과 실제 삭제/복원 완료, 장치 전체 데이터 소거까지 완료된 것으로 확대하지 않는다. 위험한 잔여 경로의 무조건 강제 삭제는 보류한다.

B5 대조에서 자비스의 `src/personal-context-store.ts`, `personal-context-evidence.ts`에 이미 문맥 예산·근거 snapshot·삭제 projection 연결이 있음을 확인했다. 다음 공통 문맥 공급은 이를 재사용하며 세션 실제 전달·중복·compaction·범위/삭제 결합을 구현해야 한다. SB에 중복 전달 원장을 신설하지 않았다. 자연어 검색, 일반 agent fence·접근 범위, 자비스 정정 UI/원본 차단 전파, 운영 전환/독립 복원과 B4~B8 전체 목표는 계속 남는다.
