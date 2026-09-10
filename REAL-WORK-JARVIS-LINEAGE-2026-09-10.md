# 실제 업무 내용의 자비스 계보 인수 — classify→승인→outbox→provider→회수

인계서 M2의 자비스 계보 부분이다. 지금까지 paired 인수는 스스로의 한계를 `limits: "fixture verified task and reviewed content"`라고 기록해 왔다. 후보 본문(subject/statement)이 JARVIS 빌드의 `tests/fixtures/scoped-outbox.js`에 하드코딩된 `"첫 결정\r\n두 번째 결정\n반복\n반복 [^user]"`였기 때문이다. **이번에 그 본문을 오늘 실제로 검증한 업무 결과로 바꿔 같은 계보를 통과시켰다.**

## 1. 실제 업무 항목

`REAL-WORK-ITEM-2026-09-10.json` (SHA-256 `caa821aa1592a6c158d187c9e3b4dc0ecca97f4c749587543992fb715c7431bd`).

내용은 오늘 실제로 수행하고 **저장 전에 검증한** 결과다: 릴리스 후보 `25d49b4367945c8fa01ea71f2d83932d8da934d8`(소스 `d4cbdda`)가 JARVIS `195b1a7` 빌드와의 paired 연동·유지보수 검사를 exit 0으로 통과했고, 이후 각주 중복 결함을 `110b474`로 수정했으며 그 트리의 전체 회귀가 1,793 passed / 2 skipped / 593.22초 / exit 0이라는 사실. 실패·미확정 결과를 성공으로 승격하지 않았다.

## 2. 실행한 것

```bash
python deploy/prepare-release.py /var/tmp/sb-final-candidate-4aa7111 --offline
python deploy/check-release-integration.py <release> /var/tmp/jarvis-current-pair-_mq15nmd/source/dist \
       --work /home/jm/orca/projects/second-brain-app/REAL-WORK-ITEM-2026-09-10.json
```

- 후보 릴리스 `c04dee1a11ff0833b634c30796924d1ea19f8a6a`, 소스/harness 커밋 `4aa7111abe5e`. wheel SHA-256은 앞선 후보와 **동일**하다. 즉 제품 코드는 그대로이고 달라진 것은 계보에 실린 본문뿐이다.
- 결과 exit 0. 원본 JSON은 [계보 결과](REAL-WORK-JARVIS-LINEAGE-2026-09-10.json).

## 3. 계보 증거

| 단계 | 값 |
|---|---|
| 후보 생성 | 운영 JARVIS CLI `memory classify`로 발행(하드코딩 review 데이터 아님) |
| 승인 | ControlPlane `signCommandApproval` → remember dispatch 승인 → claim → scope proposal → scope review 승인 |
| 접수 | `admission: accepted`, request `memreq:scoped:v4:a12e34b4f5e17283ecebb4d31a9cdead960c17118c520dd57915cdd6e675857c` |
| 멱등키 | `memidem:scoped:v4:a4c0ca330a9e9186fd151e7114e7f1c5acc38a693fecbf191ed6d540c652b7d9`, `replayed: false` |
| 큐 | `pending/memreq:scoped:v4:a12e34b4….v4.json` |
| 실행 | `provider_state: proved`, dispatch attempts 1, `foreign_key_errors: 0` |
| 정산 | JARVIS `settled`, control command `completed`, 재전송에도 settlements 1 / attempts 1 |
| 회수 | 새 reader 로그인으로 context record 1건, `sbrecord:v1:b946ac451c21475428dadbed40981072d032ea4293a764d19c0477fa17c576db`, `same_generation: true`, 출처 표기 `Second Brain` |
| 독립 클라이언트 | stdio 클라이언트 2개가 각각 1건 회수 |
| 거부 | reader 정책 철회 후 조회 **403** |

## 4. 실제 본문이 저장 바이트까지 도달했는지

기존 harness는 본문을 검사하지 않았다. 이번에 `REAL_WORK_BODY_NOT_STORED` 검사를 추가해 실제 릴리스 해시 `25d49b4367945c8fa01ea71f2d83932d8da934d8`이 provider가 실제로 쓴 바이트에 있는지 확인했고, 세대 `sbgen:v1:ca740f1246d24d7f8808abac4ea64d62ac5aa4bcb1a40de625192bc4e307ae1c`의 다음 세 곳에서 발견했다.

- `raw/86/8690422df27d8cf0c356c9c5552b641ede566db3898800715b9e1802cff2902e` (CAS 원본)
- `wiki/memory-28aa995a59e12dd5864412b75bc3916daa933ac6c4614568954ec25561a79746.md` (컴파일된 페이지)
- `.sb/search.db` (검색 색인)

## 5. 검사를 완화하지 않았다는 근거

- 같은 릴리스에서 `--work` 없이 표준 gate를 다시 실행해 exit 0을 받았다([표준 gate 결과](REAL-WORK-JARVIS-STANDARD-GATE-2026-09-10.json)). 4개 모드(`valid`/`revoke_during_accept`/`revoke_before_execute`/`expire_before_execute`)가 그대로 돌고, `content_profile: fixture`, `limits` 문구도 종전과 **글자 그대로 동일**하다.
- 회수 검사에서 바꾼 것은 검색어뿐이다. 하드코딩된 `'결정'`은 fixture 본문에만 있는 토큰이라, 실제 업무 항목은 정상 정산된 뒤 검색 단정에서만 실패했다. 이제 검색어는 검사 대상 본문에서 온다(`query: "릴리스"`, 실행 전 statement 포함 여부 확인). `records.length > 0`, 각 record 텍스트가 기록된 payload의 부분문자열일 것, 같은 generation, 철회 후 403은 모두 그대로다.
- `--work`는 `valid` 모드만 돈다. 철회·만료 모드는 본문과 무관한 정책 수명 검사이며 같은 릴리스의 표준 gate가 덮는다.

## 6. 이 실행의 한계

- **신원·정책·시각은 여전히 fixture다**(`principal:owner`, `agent:fixture`, `agent:reader`, `policy:1`, clock `2026-08-28T12:00:00Z`). 실제인 것은 업무 내용과 그것이 통과한 제품 경로다. 결과 JSON의 `limits`도 이제 그렇게 기록한다: `real verified work item content; fixture forwarding identity, policy and clock; native submission is reported separately; not operational deployment`.
- `production_activated: false`. 운영 `current`·운영 DB·운영 서비스를 바꾸지 않았다.
- native 모델 호출 0.

## 7. 운영 자비스로는 왜 아직 못 하는가

운영 authority 릴리스 `a3cbbbe1604798052db6051a8751f039573eb126`의 `dist/src`에는 모듈이 371개인데, 이번에 쓴 `195b1a7` 빌드에는 516개다. **memory 관련 77개 모듈이 운영 릴리스에 없다** — `cli-memory-intake.js`, `cli-memory-reference.js`, `cli-memory-scoped-reconcile.js`, `memory-candidate-scope.js`, `memory-candidate-dispatch-recovery.js` 등. 즉 운영 authority에서는 `memory classify/stage-dispatch/outbox` 명령 자체가 존재하지 않는다.

따라서 위 계보를 **운영 자비스에서** 재현하려면 새 authority 릴리스 활성화가 선행되어야 하며, 그것은 인계서 9절의 보류 대상(실제 writer 배제·복구 조건 필요)이다. 이번 작업에서 전환하지 않았다.

## 8. 회귀 범위

`110b474`(전체 1,793 passed / 2 skipped) 이후 `sb/`와 `tests/`는 **한 파일도 바뀌지 않았다**. 이번 변경은 문서, 업무 항목 JSON, `deploy/check-release-integration.py`, 그리고 pytest가 참조하지 않는 두 acceptance 스크립트뿐이다(`grep -rl` 결과 0건). 그러므로 그 전체 회귀 결과가 현재 제품 코드를 그대로 덮는다. 변경한 스크립트는 `node --check` 통과와 위 두 gate 실행으로 검증했다.
