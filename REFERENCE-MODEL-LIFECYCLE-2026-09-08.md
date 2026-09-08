# 실제 모델 소비의 정정·삭제와 보관된 문맥의 한계

인수 도구 커밋: `8cb5dd5`. 세컨드브레인 제품은 `701e966`, 자비스 격리 빌드 기준은
`110227e23181f2370478e2840787cd1ede349b1a`다. 자비스 작업공간과 운영 DB/서비스는 수정하지 않았다.

**새 조회를 통한 실제 모델의 정정·삭제 반영은 통과했다. 삭제 전에 보관한 문맥을 다시 보내면
모델이 과거 값을 다시 답하는 것도 재현했다. 세션 무효화와 자동 주입의 전체 인수는 미완료다.**

## 1. 실행한 경로

임시 SB provider와 자비스 DB에 합성 기억 한 개를 만들었다. 실행 중 생성한 128-bit 확인값을
기억 본문에만 넣고 자비스 실제 `memory context` CLI→MCP→reference JSON→native Codex
모델 요청을 연결했다. 정정 시 독립적인 새 확인값을 생성했다. 도구 없는 각 요청은 별도
ephemeral 세션이며 실제 운영 자료를 모델에 보내지 않았다.

정정·삭제는 자비스의 기존 target resolve, tombstone chain, V2 요청 생성과 `sb_write_request`,
SB 실제 executor를 거쳤다. `proved` 결과의 disposition proof와 observation manifest를
자비스 검증기로 확인했다. 사용자 승인 부분은 기존 synthetic owner fixture이며 실제 화면·
Control Plane 전체 인수로 보고하지 않는다. 수집/compile도 이 probe의 합성 seed 경로다.

## 2. 실제 결과

| 모델 요청 | 입력/기대 | 결과 | 모델 호출 시간 |
|---|---|---|---:|
| 빈 조회 | 기록 없음 | `no_data`, 답/출처 필드 모두 null | 6,815 ms |
| 최초 기억 | 첫 확인값과 근거 record | 정확한 값·record/digest/source/generation 일치 | 13,377 ms |
| 정정 후 새 조회 | 새 확인값만 포함 | 새 값과 새 근거 일치, 이전 값 미포함 | 12,993 ms |
| 삭제 후 새 조회 | record 0개 | `no_data`, 답/출처 필드 모두 null | 7,139 ms |
| 삭제 전 사본 재전송 | 최초에 보관한 payload를 의도적으로 다시 제출 | 과거 확인값을 다시 답함 | 14,981 ms |

다섯 호출 모두 다른 native thread ID이며 `turn.completed`와 process exit 0을 확인했다.
도구 호출·오류·완료 없는 응답은 기존 event 감사기로 거부했다. 이 수치는 합성 단일 실행의
모델 호출 시간이며 CLI 검색 지연이나 운영 p95가 아니다.

정정/삭제 high-water는 각각 1/2이며 proof/관측 검증이 통과했다. 과거 사본 probe 이후에도
새 조회의 record는 0개였다. 즉, SB에서 삭제 기억이 검색으로 재등장한 것이 아니다.
삭제된 사본을 소비자가 다시 전송한 경로의 문제이며 모델의 거짓 기억 생성으로 분류하지 않는다.

모델 요청 후 자비스 `personal_context_snapshots`, `personal_context_memory_evidence`,
`memory_projection_dependencies`는 각각 **0행**이었다. 기존 CLI는 참조 읽기 경로이고
해당 실행에 대한 제품 전달 원장·projection은 만들지 않는다. 다른 모든 테이블 또는 다른
앱에 전송 이력이 전혀 없다는 전역 주장으로 확대하지 않는다.

## 3. 검증 범위와 재현

- Python 계약·효과·두 프로세스·수명주기 회귀: **18 passed**, 8.84초.
- native model event 감사기: **14 passed**.
- Ruff `sb tests`, 변경 fixture 타입 검사, 두 Node 스크립트 syntax 검사 통과.
- 새 자비스 outDir에 tsc 컴파일 및 기존 migration/contract 복사 완료. 이전 dist를 재사용하지 않았다.
- 자비스 소스 identity를 빌드 전후 비교했고, 실행 중 SB Python 제품과 자비스 compiled JS의
  해시 불변을 확인했다. build manifest와 native 결과는 [JSON](REFERENCE-MODEL-LIFECYCLE-2026-09-08.json)에 보존했다.

초기 집중 테스트 명령은 존재하지 않는 파일 하나를 지정하여 exit 4였고 테스트가 실행되지 않았다.
실제 파일 목록 확인 후 위 네 모듈에서 18개가 통과했다. 제품 결함 또는 통과한 검사로 계산하지 않는다.

```bash
cd /home/jm/orca/projects/second-brain-app
TMPDIR=/var/tmp node scripts/jarvis-reference-model-acceptance.mjs /var/tmp/sb-reference-lifecycle-build-SRjvc0 --lifecycle
```

실행에는 설치된 Codex CLI와 로그인, 새 자비스 빌드의 migration/contract 및 의존성이 필요하다.
원시 결과는 `/var/tmp/sb-reference-model-PdJnxL/result.json`, 실행 로그는
`/var/tmp/sb-reference-model-lifecycle.log`다. `--lifecycle` 없이 기존 두 호출 인수도 유지한다.
fixture의 `--live-clock`은 marker가 있는 격리 저장소의 명시적 apply에만 허용한다. 기본 결정적 시각은 유지한다.

## 4. 다음 구현과 보류 판정

이번 증거로 C7을 provider 삭제 검사만으로 완료 처리할 수 없음을 확인했다.
[전달 수명 계약안](REFERENCE-DELIVERY-LIFECYCLE-CONTRACT-2026-09-08.md)에 다음을 구체화했다.

1. 실제 제출 직전 generation·privacy·suppression·만료 재검사.
2. 실제 client/session/epoch와 payload digest를 묶는 전송 claim·확인·불확실 상태.
3. 삭제·정정 시 기존 전달 계보 무효화와 늦은 확인으로 재활성화하지 않는 처리.
4. 실제 compaction/new session 관측 후 최신 기억 재공급. 오래된 payload 복사 금지.
5. 이미 보낸 내용의 회수가 불가능한 client에서는 기존 문맥으로 후속 자동 실행을 계속하지 않는 경로.

해당 구현 전 전역 자동 주입·세션 중복 억제를 활성화하지 않는다. 현재 인수 스크립트는
제품 전달 서비스가 아니다. 새로운 별도 기억 DB나 SB 권한 엔진으로 소비자 공백을 우회하지 않는다.
프로젝트 범위·원본 차단 전파·실제 사용자 질문·GUI·운영/DR 인수의 기존 전체 조건도 유지한다.
