# 운영 전환 준비서 — JARVIS authority와 SB provider

작성 기준: [인계 보완](CODEX-REPLY-REVIEW-2026-09-10.md) 5.1. 검토 커밋 `a6b3620`. **이 문서는 전환을 실행하지 않는다.** 서비스·`current`·운영 DB·설정을 바꾸지 않았고, 중단 판단의 대상이 되는 고정값만 기록한다.

관측 시각(대기열): `2026-09-10T11:24:40.852018+00:00`, `deploy/check-jarvis-pending-state.py` exit 0, `drain_authorized=false`. wheel SHA는 같은 세션에서 `sha256sum`으로 재확인했다.

## 1. 전환 대상 후보 — 해시가 맞는 manifest만 사용

| 역할 | 소스 커밋 | release_id | wheel SHA-256 | 재료화 경로 |
|---|---|---|---|---|
| **전환 대상 SB** | `4aa7111abe5e58e27d70f77bdf3bd55335348275` | `c04dee1a11ff0833b634c30796924d1ea19f8a6a` | `ac8fcd1655356124ec0c51b56b9e23cc4b9054ede9283649fd2fecb4703502ca` | `/var/tmp/sb-final-candidate-4aa7111/releases/c04dee1a11ff0833b634c30796924d1ea19f8a6a` |
| 이전 격리 후보 SB (업무 본문 인용용) | `d4cbdda68932b788f91b462d283249b84779e344` | `25d49b4367945c8fa01ea71f2d83932d8da934d8` | `aa6fad5fc76ebda509ad3ac616b4e94b538bad2ae2161c83b86158a09a886dcf` | `/var/tmp/sb-cursor-candidate-d4cbdda/releases/25d49b4367945c8fa01ea71f2d83932d8da934d8` |
| **현재 운영 SB** | `0ef3866d29179fd2da4d235737c99a1e311ddb3c` | `41f0751aca8906d612961e704bc60dd0855fdabd` | `5fc0f688ec19950f9b674c351db8097b54a1ee6be6c92f36258033d0a0907fa1` | `/home/jm/.local/state/second-brain/app/releases/41f0751aca8906d612961e704bc60dd0855fdabd` |

두 후보 wheel은 서로 다르다. 실제 업무 JSON 안에 인용된 `25d49b4`/`aa6fad5f…`는 **이전 후보**이고, 표준 gate·쓰기비용 실험이 돌린 **실행 중 후보**는 `c04dee1`/`ac8fcd16…`이다. 운영 전환 대상은 후자다. `d4cbdda`까지 “110b474 이후 제품 동일”을 확장하지 않는다.

대상 후보 공통 입력(재현 핀):

- `release_id_scheme`: `sb-release-inputs-v3`
- `source_materialization`: `git-archive`
- `contract_profile`: `task32-schema4`
- `requirements_sha256`: `75ce0da3bace37b8e20a733acd1b1cc7db5c30c77586baa59eef8bdf18245177` (운영 릴리스와 동일)
- `preparation_recipe_sha256`: `4742bcc1cbc897082e1e44a5f7fdf7580767ba42aaa46405fbd8058b334ab775`
- `python_runtime_input_sha256`: `f58cbec1d5c0281f4ec1c1a85a5b449f5bc13d33304b97acca4a342b92a6d3dd`

`4aa7111` 이후 HEAD(`a6b3620`)의 제품 코드 차이는 `tests/test_mcp_scoped.py` +12줄뿐이다. 전환 wheel을 HEAD로 다시 굽지 않는다. 문서·M3/M5 테스트 커밋은 설치 대상이 아니다.

운영 소스 `0ef3866` → 대상 `4aa7111`는 `sb`/`deploy`/`tests` 기준 403 files / +45777 / −902. 운영 wheel을 “거의 같은 후보”로 취급하지 않는다.

## 2. SB provider 고정값

| 항목 | 현재 운영 | 전환 후 목표 | 되돌리기 |
|---|---|---|---|
| `current` | `/home/jm/.local/state/second-brain/app/current` → `releases/41f0751aca8906d612961e704bc60dd0855fdabd` (2026-09-07 21:33) | 같은 `releases/` 아래에 `c04dee1…`를 **복사·검증한 뒤** 심볼릭 링크만 교체 | 링크를 `41f0751…`로 되돌린다. 디렉터리는 삭제하지 않는다 |
| writer | `app/writer` 없음. 작성은 `bin/sb`와 `jm-second-brain-requests.service`(`apply-requests --once`) | 동일 유닛이 새 `current/bin/sb`를 가리키게 됨 | 링크 복원으로 이전 바이너리 복귀 |
| CLI | `/home/jm/.local/bin/sb` → `app/current/bin/sb` | 변경 없음(심볼릭 링크 경유) | 동일 |
| 설정 | `/home/jm/.config/second-brain/config.toml`; `provider_release_sha = "41f0751aca8906d612961e704bc60dd0855fdabd"` | 링크 교체와 **같은 절차에서** `provider_release_sha`를 `c04dee1a11ff0833b634c30796924d1ea19f8a6a`로 맞춘다 | 설정 백업본과 함께 복원 |
| 상태/요청 | `state_root=/home/jm/.local/state/second-brain`; `request_root=…/requests` | 경로 유지. pending/processing/receipts 파일 수 이번 관측 0 | 경로 유지 |
| vault | `share/vault` → `vault-generations/sbgen:v1:8dbef8a6877a232b46ff75b8b97c30f439010f94c14dd0f601d84beb248b36ea` | 세대 포인터를 전환 스크립트가 임의로 옮기지 않는다 | 세대 디렉터리 보존. 복원은 `sb restore` 정본 절차만 |
| DB | 세대 `.sb/ledger.db`, `search.db`, `vectors.db`; 상태 `generation-journal.db`, `requests/journal.db` | 동일 파일. 스키마 마이그레이션을 전환 순간에 가정하지 않는다 | 저널/세대는 백업 세트와 함께 |
| 백업 | `backup_root=/home/jm/.local/state/second-brain/backups`; 최근 `second-brain-20260910T032857+0900.tar.gz` | 전환 **직전** 동일 명령으로 한 세트 추가 | 해당 tarball + sha256 |
| 서비스 | `jm-second-brain-requests.path` active/waiting; refresh/maintenance/backup 타이머는 대기. 상시 `second-brain.service` 없음 | 링크 교체 전 path/timer를 멈추고 pending이 비었는지 재확인 | 유닛 재개 |

락: `state/.sb/run.lock` 존재(빈 파일). 전환 전 `sb` 실행 프로세스와 refresh 엔트리를 배제해야 한다. 큐 0은 배제 증거가 아니다.

## 3. JARVIS authority / control-center 고정값

| 항목 | 현재 운영 | 격리 인수에 쓴 빌드 | 되돌리기 |
|---|---|---|---|
| authority `current` | `/home/jm/.local/state/orca-jarvis/authority/current` → `releases/a3cbbbe1604798052db6051a8751f039573eb126` | `/var/tmp/jarvis-current-pair-_mq15nmd/source/dist`, 소스 `195b1a7d4588a8386def5e7dce2067a141942708`, archive SHA-256 `40e0ed0fccaa10d549e8945a6113be7c42676344b70c2a969c49c65231e8d333` | 링크를 `a3cbbbe…`로 복원 |
| authority 영수증 | `activated_at=2026-09-03T14:52:02.203164Z`, `source_head=7023f7cbc9c301ba118e739b1a2efe443bf78fd8`, `verified=true` | 운영 릴리스가 아님. 페어 빌드는 임시 `/var/tmp` | 운영 영수증을 덮어쓰지 말 것 |
| control-center `current` | `releases/artifact-4146a192b5fb9e489e2ce3fcb9629077739df0134bc26094750628369dcfdb98` | 이 artifact는 [의존성 재사용 보류](RELEASE-PREPARATION-GAPS-2026-09-09.md)에서 lock mismatch로 새 MCP SDK 재사용이 거부된 그 운영본이다 | 링크 복원 |
| CC 영수증 | `activated_at=2026-09-07T07:41:24.021807Z`, `source_head=331c92e26810f8d762453a8e2dd043448f747c36` | 새 dependency artifact가 없으면 페어 빌드를 운영 CC에 올리지 않는다 | 동일 |
| DB | `/home/jm/.local/state/orca-jarvis/jarvis.sqlite` (+ WAL/SHM, 이 세션에서 mtime 갱신 중) | 경로 유지. 페어 빌드 스키마를 운영 DB에 가정하지 않는다 | 아래 백업 |
| 백업 | `…/orca-jarvis/backups/`, 15분 타이머 `jm-jarvis-backup.timer` active. 최근 파일 `jarvis-20260910T111500099Z-96475324293394b2.sqlite` | 전환 직전 `--production` 백업 1회 추가 | 해당 sqlite 세트 |
| 서비스 | `jm-jarvis.service` active, `jm-jarvis-dashboard.service` active, `jm-jarvis-phone-gateway.service` active | 전환 시 세 유닛을 정지한 뒤에만 DB 핸들 재검사 | 유닛 재시작 |
| 진입점 | authority: `dist/src/cli.js service run --db …/jarvis.sqlite`; dashboard 127.0.0.1:4173; phone 127.0.0.1:4176 | 새 릴리스의 동일 명령 경로를 영수증으로 고정한 뒤에만 교체 | 이전 `current` |

`jarvis-side-notch-gateway.service`는 별도 프로젝트(`/home/jm/orca/projects/jarvis-side-notch`)이며 이번 SB/authority 전환 집합이 아니다.

## 4. 모듈·결함 재측정 — 다시 만들지 말 것

### 4.1 `_proposed` 우회 (결함 C)

운영 세대 `sbgen:v1:8dbef8a6…`의 `.sb/compiled`는 **없다**. `generation_staging._copy_compiled_markers`는 운영 wheel에 없고 후보 `c04dee1`에 있다. 같은 입력으로 운영 `41f0751`는 compiled marker를 복사하지 않고 후보는 복사한다는 기존 대조를 유지한다.

따라서 이 수정은 후보에 이미 있다. 전환 전에 동일 패치를 운영 트리에 다시 넣지 않는다. 전환 후에도 **현재 활성 세대에는 compiled가 없다.** 링크 교체만으로 기존 페이지의 `_proposed` 우회가 즉시 사라지지 않는다. 첫 정상 compile/세대 전이가 marker를 심는 절차를 전환 런북에 넣기 전에는 활성화 성공으로 치지 않는다.

### 4.2 운영 authority “memory 모듈 부재”

Claude 관측을 재측정했다. 운영 authority `dist/src`에 memory 관련 `.js`가 **없다**는 말은 사실이 아니다.

| 빌드 | `dist/src/*.js` | `memory-*` 또는 `second-brain*` |
|---|---|---|
| 운영 `a3cbbbe` / `7023f7c` | 369 | 125 |
| 페어 `195b1a7` | 513 | 198 |

운영에만 있는 JS는 0개. 페어에만 있는 JS는 144개이며, 그 안에 `memory-scoped-write-*.js`, `memory-scoped-settlement*.js`, `memory-outbox-production.js`, `memory-access-claim-production.js` 등 **scoped/production 스택**이 있다. 활성화 준비 시 실행 경로·명령 진입점·실제 import를 다시 고정해야 한다. 모듈 개수 차이만으로 활성화 후 연결이 정상이라고 단정하지 않는다.

### 4.3 `activated` 잔여 3행

상태 기계는 운영/후보에 같다. 격리에서는 다음 성공 쓰기가 잔여를 정리했고, 운영 3행은 열린 항목이다. 전환이 이 행을 고친다고 가정하지 않는다. 측정은 [쓰기 비용](WRITE-COST-AND-INTERRUPT-2026-09-10.md).

## 5. 중단·전환 허가 조건 (아직 미충족)

다음을 **한 번의 전환 창**에서 모두 만족하기 전에는 운영 중단/링크 교체를 하지 않는다.

1. `check-jarvis-pending-state.py`가 명명 큐 전부 빈 집계, `active_cursor_rows=0`, **그리고** `drain_authorized`가 절차상 명시적으로 true가 되는 별도 승인. 이번 값은 `drain_authorized=false`, GJC unexpired lease **1**.
2. `check-database-handles.py`에서 `jarvis.sqlite`/WAL/SHM을 연 프로세스가 **정지 후** 0. 현재는 dashboard·authority가 파일을 들고 있다(이전 관측 PID는 재사용하지 말 것).
3. SB `requests/pending` 비어 있음(이번 0) + `run.lock` 보유 프로세스 없음 + refresh/maintenance/backup oneshot 미실행.
4. JARVIS `195b1a7`(또는 그 이후로 고정한 새 source_head)용 **새 dependency artifact**. 운영 CC `artifact-4146a…`에 페어 dist를 섞지 않는다.
5. SB 후보를 `app/releases/c04dee1…`로 복사한 뒤 wheel SHA·`release-manifest.json`·`bin/sb --help`·오프라인 doctor가 후보와 바이트 일치.
6. 설정 `provider_release_sha` 변경 문안과 롤백 문안이 같은 체크리스트에 있다.
7. 전환 직전 SB tarball + JARVIS `--production` sqlite 백업의 sha256이 이 문서 표에 추가된다.

큐가 비었다는 사실만으로 writer 배제나 전환 승인으로 해석하지 않는다. 이전 [OPS-RECHECK](OPS-RECHECK-2026-09-10-0140.md)와 같다.

## 6. 활성화 이후에도 인수가 아닌 것

전환 허가가 나더라도 활성화 자체는 인수가 아니다. 이어서 [인계 보완 5.2](CODEX-REPLY-REVIEW-2026-09-10.md): fixture가 아닌 실제 principal/agent/session으로 classify → candidate → outbox → provider → settlement → 새 세션 회수·철회를 **같은 업무 ID**로 검증한다.

M3·M5는 이 전환과 병행 준비한다. 운영 기억/클라이언트 사본을 지우기 전에 격리에서 삭제·재개·복원을 구체화한다. 초안: [M3 복원 설계](M3-RESTORE-DESIGN-2026-09-10.md), [M5 사본 정책](M5-COPY-POLICY-2026-09-10.md).

## 7. 판정

- 전환 대상 SB 후보는 `c04dee1` / `4aa7111` / wheel `ac8fcd16…`로 고정한다.
- 운영 SB는 `41f0751` / `0ef3866` / wheel `5fc0f688…`이며 후보와 제품이 다르다.
- 운영 JARVIS authority는 `7023f7c`/`a3cbbbe`, 격리 페어는 `195b1a7`이며 scoped memory 모듈이 운영에 없다.
- **운영 전환은 보류.** `drain_authorized=false`, 라이브 DB 핸들, CC 의존성 artifact 미준비, 현재 세대 compiled marker 부재.

현재 판정은 인계 보완과 같다: 공유 기억의 실제 사용 증거는 강화됐지만 JARVIS 및 여러 에이전트의 운영 메인 기억 저장소 전체 완성은 아니다.
