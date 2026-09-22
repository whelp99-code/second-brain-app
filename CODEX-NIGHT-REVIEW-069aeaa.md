# 고정 제출 069aeaa 독립 검토

작성자: **기존 지정 감시 Codex `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`**. 2026-09-13T07:39:12.536649+00:00. 원래 Codex는 조정만 했고 아래 직접 검증은 본 기존 작업에서 수행했다.

**판정: N3 및 record 보존 일부 해결. SB 정상 N2 두 결함과 N4 문서 잔여로 일반 인수 미통과, 원 전체 제품/운영 인수 미완료.** completion/remaining-triage/progress-control과 원 A–F/M1–M14 유지. 콘텐츠 안내 뒤의 정상 범위는 원래 Codex의 조정 결정이며 사용자 목표 축소가 아니다.

## 고정 출처

- 제출 HEAD `069aeaa7c193dbdd177b004767ded559cec1a07f`, SB source `6b01c2e6d29b98196fe74ff862fb7ad063d2f137`. archive SHA256 `980f6c6cccd978183fb031fead9202857c7f350370f54ccf9ce5b5e2cce97f2c`.
- 후보 `/var/tmp/sb-candidate-6b01c2e/releases/fc2507ed0c4246da550fc2971516077c4ee66cd7`; wheel SHA256 `c6278e7ee26dcfb0823b0ef51dcf6c3d57521712f04a6dcab28888eedba08694`. **183 Python 파일 source/wheel/installed 바이트 일치**.
- JARVIS `64715bade176f5724bc4ebe8a40bc6f4c8f49a96`, archive SHA256 `1f1beaaf7a15abb645145a9c939a34b6fe13ceb37e1cfadf59aa36643c6eae36`. 제출 source tracked 바이트 일치. **새 dist 1,216개 SHA 일치**, digest `sha256:c64cfbf1c57f469927a453b1784b05508e33c9186f656a6546de86226e6aff36`. frozen archive backend 재빌드도 같은 1,216개 내용 일치. mode 104개 차이를 별도 기록했고 byte 불일치로 오인하지 않았다. 메타데이터 dirty:true는 그대로 보존한다.
- `/var/tmp/jarvis-artifact-64715ba/runtime`은 `78e7307/runtime` 링크다. **5,787 runtime 파일 모두 b279068 원 SHA 목록과 동일**, runtime/package-lock도 이번 source/package-lock과 동일. 이전 dist를 새 구현 검증으로 쓰지 않았다. 새 `bin/jarvis --help` EXIT0. 고정 경로 실행 확인이며 artifact 이동/운영 전환 인수는 아니다.
- 종료 대조 HEAD 동일, 양쪽 제품/테스트/scripts/deploy 바이트 변경 없음. `identity.json`, `runtime-files.json`, `dist-rebuild-comparison.json`, `post-source-check.json`, `harness-sha256.json`과 원 archive/log는 `/var/tmp/codex-night-069aeaa-080q44i1`에 있다. b279068 및 이전 원본은 보존하고 복사본만 수정했다.

## 직접 검사와 보존

| 직접 검사 | 결과 | 원본 |
|---|---|---|
| SB 변경 hook | 12 passed / 4.64s | sb-tests.log/json |
| Ruff | EXIT0 | sb-ruff.log/json |
| SB 변경 파일 타입 | **0 errors / 12 warnings / EXIT1** | sb-types.log/json |
| JARVIS hook | 10 passed / 총 10.28s | jarvis-tests.log/json |
| 영향 받는 명시 dispatch 정상 3개 | 3 passed, 나머지 21개 이름으로 선택 제외 / 총 5.01s | dispatch-normal.log/json |
| ESLint | EXIT0 | jarvis-lint.log/json |
| source-bound backend build (TypeScript 포함) | EXIT0 / wall 9.9638s | jarvis-build.log/json |
| 제출 launcher | --help EXIT0 | submitted-cli-help.json |

현재 변경은 최종 record 직렬화와 공유 dispatch 변환에 영향을 주므로 관련 hook/dispatch/예산 검사를 수행했다. 이전 전체86/DR/일반 성능·보류 검사를 반복하지 않았다. Grok 자체 10+3, 과거 b279068 11+9+3과 합산하지 않는다. 아래 probe 관측은 pytest 성공 수에 더하지 않는다. 타입 EXIT1은 완전 통과가 아니다.

## N2 통과 범위와 잔여

### 보존된 실제 record와 JARVIS 정상 재선택

SB 단일 인용 fixture는 이제 원 `record_id`와 `record_digest`를 최종 추가 문맥에 출력하며, 이전 CAS hash 오인은 수정됐다(`sb-identity-probe.json`). JARVIS command consumer의 최종 memory_ref/version도 실제 원 record_id/digest와 같고 기존 출처 변환을 보존한다(`jarvis-probe.json`).

`probe-jarvis-correction.mjs`에서는 합성 provider가 정상 정정된 record와 새 generation 응답을 제공한 후 동일 session/prompt의 새 c2 이벤트를 제품 dispatcher→실제 command consumer로 전달했다. 최초 record `…14bceffe…`가 새 record `…4875afb8…`로 바뀌고 새 요청에는 `Omega corrected ordinary memory.`와 그 digest만 있다. 요청은 각각 488/475bytes. **합성 provider 응답 + 실제 dispatcher/consumer 프로세스 경계 검증**이며 실제 SB MCP/native 모델 실행으로 치환하지 않는다.

### N2a: 두 인용 페이지에서 본문과 식별자·출처가 서로 어긋남

`probe-correction.py`의 `two_citation`은 일반 Vault.write_pages로 두 정상 인용을 가진 페이지를 쓰고 committed 바이트에서 실제 records를 읽었다. Alpha 문장은 `fixture:alpha.md`/record `sbrecord:v1:047a80a9aa05278a5c03fcb02c94fc65d94373ff81152bca12d3988284055f64`, OmegaUniqueTarget 문장은 `fixture:omega.md`/record `sbrecord:v1:c4928195809c3b377fd314801097613dd16f9717390b9013ebf68256376231bd`이다.

설치 CLI에 query `OmegaUniqueTarget`인 정상 PostCompact→UserPromptSubmit을 보내면 두 문장이 담긴 snippet 전체에 **Alpha의 record_id/version/source_ref 하나만** 붙는다. `_identity`는 snippet에 포함되는 첫 record를 고르고 `_serialize`는 원 snippet을 그대로 출력한다(`sb/postcompact_hook.py:173–199,213–246`). 존재하는 record digest를 붙이는 것만으로 본문/record 관계가 맞아진 것은 아니다.

완료조건: 최종 excerpt를 실제 선택된 record 본문·식별자·인용 출처와 묶어야 한다. 다중 record 페이지에서도 목표 본문을 회수하고, record와 무관한 첫 항목 fallback/여러 본문에 단일 잘못된 식별자 부여를 피한다. 정상 정정 재선택과 최종 직렬화 예산을 함께 검증한다. 코드 수정은 Grok만 한다.

증거 `correction-probe.json`의 `two_citation`, 실제 설치 CLI stdout과 committed records. 일반 인용 조립 검사이며 보안/삭제/경합 검사가 아니다.

### N2b: 정상 managed vault 진입점이 세션 상태 저장에서 실패

`probe-correction-scoped.py`는 모든 vault/share/state/request/registry 경로를 새 합성 fixture로 지정하고, 원문 Alpha 저장→실제 run_ingest/run_compile→원문 Omega 정정→같은 정상 파이프라인을 수행했다. LLM 응답만 정상 본문을 반환하는 합성 응답이다. ingest/compile은 두 단계 모두 EXIT0이고 실제 committed record/세대가 갱신됐다.

하지만 **각 단계의 설치 CLI PostCompact와 UserPromptSubmit은 EXIT1**이다. `sb/cli.py:295`가 넘긴 검색 generation root를 `_stage_path`(`sb/postcompact_hook.py:263–267`)가 세션 상태 디렉터리로도 사용해 `…/share/vault-generations/<generation>/.sb/session-memory` mkdir에서 PermissionError를 낸다. 단순 writable `_seed` fixture가 정상 제품 managed 경로를 대표하지 못했다. 실제 모델 요청까지 갔다는 증거는 없다.

완료조건: 기존 config의 정상 mutable 세션 상태 위치를 지식 generation 읽기 위치와 분리해 정상 제품 진입점에 연결한다. 새 세대 정정 후에도 같은 세션의 stage/출력 확인/재전달 의미를 유지한다. **봉인 generation 제자리 수정/chmod로 해결하지 않는다.** 정상 원문 저장/정정→설치 hook 경로만 검증하며 보류 경계/삭제/경합/복원 검사를 의뢰하지 않는다.

`correction-scoped-probe.json/.log`가 판정 정본이다. 최초 `probe-correction.py`의 pipeline 부분은 CLI registry/request 경로를 명시하지 않았으므로 보충 완결한 scoped 실행과 구별한다. 그 최초 시도는 별도 성공/결함 수로 합산하지 않았고 원본을 보존했다. 세대 실패를 확인한 뒤 권한 우회나 직접 세대 쓰기 검사를 하지 않았다.

## N3 — 제공된 occurrence 범위 해결

동일 session/prompt/summary에서 c1→c2가 SB 설치 CLI와 JARVIS 제품 dispatcher→consumer 양쪽에서 다시 전달됐다. 동일 전체 키 재전달은 억제됐고 다른 session은 구분됐다. consumer EXIT1의 `MODEL_TRANSPORT_UNAVAILABLE` 후 동일 이벤트 EXIT0 재시도도 수락됐다. `sb-identity-probe.json`, `jarvis-probe.json`에 이벤트/결과/최종 요청 보존.

이는 **제공된 명시 ID**의 정상 구분 통과다. 실제 native가 모든 occurrence ID를 제공한다는 뜻이 아니며 ID 없는 동일 이벤트 구분이나 native exactly-once를 주장하지 않는다. N3만을 위해 다시 구현을 의뢰하지 않는다. 수정 시 통과 범위를 보존한다.

## N4 — 개선됐지만 현재 핀·명령·writer/복구 자료가 아직 불완전

실제 AUTH_DB 위치, stop 전 관측/stop 후 배제 구분, 구버전 바이너리 자동 재시작 금지를 고친 점은 인정한다. 새 artifact의 source/dist/runtime/실행 증거도 통과다. 다음은 **기존 문서/공개 service/config/parser의 읽기 대조만**이며 운영이나 보류 검증 실행이 아니다.

- 운영 자료:36의 성공 명령은 여전히 `/var/tmp/jarvis-artifact-78e7307/bin/jarvis --help`다. 이번 실행 핀은 `64715ba`다. runtime 재사용은 old dist 사용의 근거가 아니다.
- :17의 SB 유닛 실제 ExecStart는 `/usr/bin/env sb run`이며 PATH에 `%h/.local/bin`이 있다. 문서가 선언한 current/bin/sb가 실제 선택되는 구성 연결은 준비되지 않았다. config의 vault/state/request/lock 대상과 기존 요청 writer/timer 범위도 ReadWritePaths 및 “active면 stop”만으로 완결되지 않는다. 공개 config의 경로 규칙과 기존 정본에 따라 확인 항목/설정 변경안을 먼저 준비해야 한다. 현재 운영 비밀 config를 읽거나 복사할 필요는 없다.
- :33–34는 새 후보 **실제 경로**, current별 명령 피연산자와 기동 명령이 생략돼 있고, :45의 “ln 실패→새 current를 만들지 않음”은 두 current 중 일부만 바뀐 상태의 다음 행동을 정하지 않는다. :46의 `sb restore --to`는 parser가 요구하는 archive와 destination 피연산자 및 정확한 백업 집합/기동 연결이 빠져 있다. 값이 외부 입력이면 이름 있는 슬롯·소유자·검증 전 중단 조건으로 명시해야 한다.
- 기존 `CUTOVER-RUNBOOK-14a6ed7-2026-09-10.md:18–25`의 SB run.lock·path/timer·pending/lease 확인과 현재 스크립트의 `drain_authorized:false` 한계를 누락 없이 연결한다. “requests/timer not-found는 설계”라는 문장만으로 대상 검토를 닫지 않는다. 실제 운영 상태는 이번에 관측하지 않았다.

완료조건은 **읽기 전용 문서 정정**이다. 현재 공개 service/config에 근거한 후보/DB/state/current/writer/명령 인자, 정지 후 조건, 실패 단계별 정지 상태와 기존 복구 제약을 하나의 승인 가능한 자료로 만든다. 당일 PID/백업 hash·운영 허가·보류 수명은 미실행/미검증으로 남긴다. restore/rollback/삭제 수명 검사를 수행하거나 대신 맡기지 않는다.

## 전체 잔여와 전달 범위

N1의 합성 consumer 수락과 SB 다음 UserPromptSubmit 경로는 원 증거로 보존한다. 자동 compaction 직후 같은 turn의 다음 모델 요청 및 로그인 native 세션은 별개 미완료/공개 계약 한계이며 새 구현 의뢰로 바꾸지 않는다. 이번 일반 검사는 원 A–F/M1–M14 전체 인수나 보류 수명 대체가 아니다.

외부 입력: 지정 실제 업무/task/원문 및 공유 대상, 격리 native 프로필/정상 로그인·consumer 구성, 실제 한글 gold/자료 크기·지연 목표, 운영 중단·전환·백업·timer 허가와 RPO/RTO. 입력 전에 수행 가능한 **N2a/N2b 정상 구현과 N4 문서**를 통합 전달한다. N3 통과·기존 정상 dispatch/stdout 실패 재시도/예산/no_data/긴 요약 통과는 보존한다.

콘텐츠 안내 관련 보안/삭제/경합/복원 수명은 보류·미검증, 안내 발생 검사는 원인 미확정이다. 재시도·수정·다른 모델/도구/세션/Grok 이전 없음. 제품 소스 수정·운영 전환·auth/config 복사·실사용자 삭제·push·새 작업/모델/주기 변경 없음. root 소유 control/야간보고에는 동시 쓰지 않고 이 검토/증거 상태만 작성했다.

전달/공식 native 재개 및 실제 착수 관측은 아래에 별도 기록한다.

## 직접 전달·공식 재개 관측

기존 Grok 대상 통합 전달 accepted:true를 받았다. 직후 화면6070888은 Goal achieved였으므로 공식 `/goal resume`를 보냈고 accepted:true를 확인했다. **화면6070999에서 Goal active/Pursuing goal**, 본 MD:1–150 읽기, 이어 `sb/postcompact_hook.py:160–279`와 재현 원본 `correction-probe.json:1–80` 읽기를 관측했다. ACK / native 활성화 / 실제 검토서 수신·도구 착수 / 소스·증거 조사 단계까지 구별한다. 제품 수정 완료나 다음 후보 인수는 아직 관측하지 않았다. 내부 thinking은 노출하지 않는다.

기존 자동화 읽기 조회에서 enabled:true/Asia-Seoul을 확인했다. 30분 주기를 포함해 설정을 변경하지 않았다. 각 ACK/screen 및 메시지는 증거 루트에 보존한다. root 소유 control/야간보고에는 동시 쓰지 않았다.
