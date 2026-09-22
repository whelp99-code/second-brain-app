# 야간 독립 검토 — 53c19c4 미통과

작성자: 기존 Codex 감시 작업 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`에 위임된 야간 독립 검증자. 원래 Codex가 직접 수행한 검토가 아니다. **제품 후보 인수 미통과, 운영 인수/전환 승인 아님.** 제품 소스/테스트는 수정하지 않았다.

## 고정 대상과 검증

- 제출 `53c19c4ddf3b40a1ab7a46a557fb1d99fbd855f3`, SB source `15f8933439bd272f5e60839a88d2609b1d005164`.
- 후보 `/var/tmp/sb-candidate-15f8933/releases/caba60cb6c304151a1e5f8e593723dbac286fa1d`.
- wheel SHA256 `ab258c894fd1827d569309dd05d66d50b345965391d184af1cbf2fbfb95979c2`.
- JARVIS `ad2d645d4f85179fc5ecf43ea2f7f012442cac4b`, `/var/tmp/jarvis-artifact-ad2d645/source/dist`.
- inventory `43438a602e055562ca8309857697264c5c2a187754c1da3b8d28d781bc2a1e98`, 34778 entries.
- 증거 `/var/tmp/codex-night-53c19c4-9vv7ixka`, 고정 archive `source/`. 검토 종료 시 두 저장소 HEAD는 위 대상과 같았다.

SB Python 182개 archive/wheel/설치물 동일. JARVIS 추적 src/tests 1133개 git 소스 동일; 별도 재컴파일 src JS 585개 dist 동일. 설치 inventory도 표준 gate에서 일치. `sb-identity.json`, `jarvis-identity.json`, `installed-standard.log`.

**이번 직접 실행:** 변경된 철회 및 관련 scoped/rollback 회귀 20 passed /15.22s; Ruff EXIT0; Python 변경 모듈 타입 0 errors/1 warning/EXIT1; JARVIS tsc EXIT0. 설치 표준/work/유지보수 각각 EXIT0. 추가 독립 boundary/factory/CLI/MCP probes 아래 참조. 과거 전체 회귀 수치를 직접 실행으로 합산하지 않는다.

Grok 원본 `/var/tmp/sb-full-pytest-15f8933.log`는 1826 passed, 2 skipped /600.76s, EXIT0을 **읽어 확인**했다. SHA/tail은 `grok-full-log-observation.json`. 결정적 잔여 결함이 있어 같은 트리 전체 회귀는 반복하지 않았다.

## N1 / V1 / R4 — 부분 개선, 실제 세션 계약 미충족 (P1)

`src/assembled-model-session.ts:12`의 새 deliver는 정상 send, accepted:false 후 한 번 재시도, 두 번 false면 MODEL_TRANSPORT_UNAVAILABLE을 이제 await한다. 독립 제출 dist의 production factory 직접 호출에서 세 경우가 각각 calls1/success, calls2/success, calls2/error로 확인됐다. no_data 입력은 빈 본문 send1, 만료 evidence는 send0/거부였다. 이 개선을 보존한다.

하지만 아래는 여전히 남는다 (`factory-session.mjs/.json`, `cli-entry.mjs/.json`, `session-references.txt`).

- production 소비자는 `src/cli-memory-reference.ts:29`가 factory를 만들고 **reader.read만 호출**한다. `deliverAssembled`의 production 호출자는 없다. CLI `memory context` 진입점은 실제 provider fixture에 status/search/read/status를 호출하여 records1을 반환했지만 주입된 model transport calls0이었다. 이 read 명령 자체에 자동 모델 전송 부작용을 요구하는 것이 아니다. 새 factory 메서드만으로 사용자 요구의 실제 세션 연결이 완성됐다는 주장을 뒷받침하지 못한다는 뜻이다.
- factory의 `deliverAssembled`는 reader의 현재 generation/권한 fence를 사용하지 않고 외부에서 준 assembler input/evidence를 바로 저장/전달한다. 같은 factory에 CURRENT_READER_DENIED를 던지는 read_fence를 주입해도 **fenceCalls0/providerCalls0/modelCalls1/delivered=true**였다. 현재 read 경로의 철회/만료/세대 검사를 이어받은 end-to-end 경로로 볼 수 없다. 이 결과를 실제 사용자 권한 우회나 외부 데이터 유출로 확대하지 않는다.
- transport가 false 반환 대신 첫 호출에서 synthetic disconnect 예외를 던지면 calls1로 끝나며 두 번째 성공 응답까지 가지 않는다. 실패 계약은 두 종류를 구분해 정규화/재시도/영구 거부 처리해야 한다. 무조건 모든 예외를 재시도하라는 지시는 아니다.

**다음 행동:** 기존 사용자 요청/세션의 실제 호출 경로를 코드 위치와 함께 먼저 특정한다. 그 경로에서 선택한 기억의 본문·출처·버전을 현재 권한/세대 확인 후 요청 경계에 연결하고 transport 결과를 처리한다. 공개 진입점으로 정상/실패/복구/새 세션/compaction/철회/만료/no_data 및 최종 JSON 예산을 함께 실행한다. factory/클래스 이름에 production/session을 붙인 추가 helper만으로 다시 제출하지 않는다. 인증이 필요 없는 주입 transport는 가능하지만 reader 및 실제 진입점 연결을 생략하는 가짜 input은 통합 증거가 아니다.

## N3 / R2 / M3 — 현재 해시 절단 방어 개선, 호환·복구 미충족 (P1)

`sb/revoked_keys.py:38-43, 72-97`의 해시 marker는 현재 형식 store의 부분 문자 절단과 **완전한 마지막 기록 한 줄 유실** 모두 UNSAFE로 거부했다. 과거 빈 파일/부분 절단 재현도 통과했다. 정상 store는 새 유효 키를 계속 허용하며 철회 키만 제외했다.

다만 독립 `marker-lifecycle.py/.json`에서 다음 두 경우를 확인했다.

1. 기존 릴리스가 만든 합법적인 `1\n` marker 호환 경로는 끝의 newline만 확인한다. `key:other\nkey:test\n`에서 마지막 한 줄이 유실되어 `key:other\n`가 남으면 **정상으로 읽어 key:test 철회를 잃는다**. 해시 marker로 만든 신규 fixture 통과만으로 구형 정본의 복원/업그레이드 안전성을 선언할 수 없다.
2. 두 번째 철회 쓰기에서 새 store replace는 끝났으나 marker replace 직전에 중단을 주입했다. 재시작 후 load는 UNSAFE, 동일 요청 record 재시도도 UNSAFE로 끝나 복구되지 않았다. 이는 fail-closed 자체가 잘못이라는 뜻이 아니다. 원래 요구의 중단/복구 및 새 쓰기 지속 계약에 준비된 회복 경로가 없다는 뜻이다.

완료 기준: 구형 정본을 근거 없이 신뢰하여 철회가 부활하지 않도록 안전한 마이그레이션/검증 경계를 정한다. store/marker 갱신 중단을 정상·신뢰 가능한 journal/복구 또는 명시된 복구 절차로 처리하고, 재시작→기존 철회 유지→새 유효 키/새 철회 쓰기 성공까지 검증한다. 불일치 marker를 현재 내용으로 덮어써서 손상을 승인하는 복구는 금지한다. 모든 재현은 격리 fixture이며 운영 정본을 건드리지 않는다.

## M11 / C·E — 실제 MCP 측정은 확인, 정정/운영 규모 근거는 미충족

검증자가 제출 `scripts/mcp-corpus-latency.py`를 복사하여 후보의 실제 stdio MCP를 새 격리 corpus에서 직접 실행했다. 과거 로그를 재인용한 수치가 아니다. 각 규모 11회, 첫 표본 포함, p95 nearest rank다 (`mcp-corpus.py`, `.log`, `mcp-corpus-result.json`).

| 페이지 | p50 초 | p95/max 초 |
|---:|---:|---:|
| 30 | 0.0572 | 0.0854 |
| 100 | 0.0839 | 0.0919 |
| 300 | 0.1757 | 0.2036 |

동시 읽기2개, 새 연결 재시도, 새 페이지 조회도 실행됐다. **한계:** 300개가 원래 운영 규모라는 근거는 없다. `RUSAGE_SELF` 85264 KiB는 빌드/검증 클라이언트 RSS이며 MCP 서버 RSS가 아니다. 1ms timeout은 완료 후 ACK만 잃는 재현과 다르다. 단계 시간/실제 timeout 여유도 아직 연결되지 않았다.

특히 스크립트의 `# correction: add a new page then search`는 기존 기억을 정정하지 않고 새 candidate_id 페이지를 하나 추가한다. 독립 probe가 이후 옛 query도 호출하니 세 규모 모두 옛 문서가 그대로 검색됐다. **새 페이지 추가의 정상 결과이며 제품 검색 결함이라고 세지 않는다. 기존 기억 정정·이전 버전 제외의 증거가 아니라는 판정이다.** 기존 동일 기억의 정정/승계 경로를 실제 MCP 읽기와 연결하고 동시 조회 중 구버전/권한 불변을 확인해야 한다.

## 보존되는 통과와 원래 요구

R1 정상 관리형 정정/사람 편집 보호 4조합, V2 cap1 실패4개 calls1 및 혼합/재시도, Unicode/줄바꿈 parity6개, N2 길이·경로 교환 순위 재현, 기존 revoke/cancellation/유실/rollback 거부를 이번 boundary probe에서 재확인했다. N4는 a7df330 검토의 정상 UI 실패→격리 설정/입력 정정→동일 버튼 성공/pages1/실제 Git 결과 증거를 보존한다. 그 UI 제품 소스는 이번 변경 대상이 아니어서 불필요하게 재실행하지 않았다. 해당 증거는 `/var/tmp/codex-night-a7df330-zli4d5wc/recovery-output-browser*`이며 영구 config/운영 복구 인수로 확대하지 않는다.

기존 A–F/R1–R7/M1–M14의 정의는 그대로다. M1 신원/권한, M2 실제 업무 공유 계보, M4 검증 결과 원계보, M5 native 사본 수명, M7 전체 읽기, M8 제품별 공유연결, M9 문맥/compaction, M10 검색품질, M13 GUI는 fixture/helper/native/운영 범위를 구별한다. M14 관계검색은 기존 보류 유지.

M6 writer 배제·전환/rollback 진입점, M12 원장/원본 유실→복원→허용/거부/high-water→새 쓰기/실제 RPO·RTO도 남는다. 이번 패키지는 DR에 과거 sealed 조회1 JSON, rollback에 단위검사 포함만 연결했다. 이것은 원래 통합 복구/전환 계약의 전체 증거가 아니다. 기존 적합한 고정 후보 증거가 있으면 연결하고, 없으면 승인 범위의 격리 실행을 마친다. 운영 drain 부재를 이 독립 준비 작업의 차단으로 확대하지 않는다.

## 다음 제출 및 재개

단일 통합 검토로 N1 실제 경로, N3 호환/복구, 위 M11/M6/M12 증거 미충족을 함께 처리한다. A–F/M1–M14 각각 verified/implemented_unverified/blocked_external/not_implemented와 구체적인 증거·실제 외부 입력을 제출한다. 작은 패치 하나 뒤 ready 응답을 반복하지 않는다. 현재 승인된 native 구현 목표를 공식 기능으로 재개하고 옛 W4 운영 blocked 목표를 복원하지 않는다.

실제 로그인·사용자 업무/프로젝트·native 세션/사본 범위·사용자 질문·운영 drain 허가는 보류한다. 제품 준비와 운영 완료는 다르며 이번 인수는 미통과다. 운영 current 보고값 `41f0751`, 직접 gate production_activated=false. 전환·인증 복사·사용자 기록 삭제·push를 수행/승인하지 않았다. 사용자에게 야간 반복 승인을 묻지 않고 기존 30분 감시를 유지한다.
