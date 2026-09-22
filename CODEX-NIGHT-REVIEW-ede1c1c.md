# 고정 제출 ede1c1c 독립 검토

작성자: **기존 지정 감시 Codex `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`**. 2026-09-13T08:07:58.423356+00:00. 원래 Codex는 조정만 수행했으며 아래 직접 검사는 본 작업에서 실행했다.

**판정: N2a 목표 record 연결 및 N2b 세션 상태 분리 해결. 정상 compile 출처 손실과 N4 문서 잔여로 일반 인수 미통과. 전체 제품/운영 인수 미완료.** completion/remaining-triage/progress-control과 원 A–F/M1–M14 유지. 콘텐츠 안내 후 정상 범위는 원래 Codex의 조정 결정이지 사용자 목표 축소가 아니다.

## 고정과 실제 바이트

- 제출 HEAD `ede1c1ce6a9d354c50625e583d20c6edc3454dff`; SB source `b9844efa06d0f9f2a5ea4168755b6621b93650ba`; archive SHA256 `6ce15654f11c04f24f3b465236fadd7afb0c6dbbc80194e0a3305374cec632b6`.
- `/var/tmp/sb-candidate-b9844ef/releases/3ae0a9a4c6db8934a814298f2ee741acc15c8349`, wheel SHA256 `f9429a95ed68790c422a8e385aeff190ad49afb8b877c643c09f71e572f2e5fe`. **183 Python 파일 source/wheel/installed 일치**. 종료 HEAD 및 제품/tests/scripts/deploy 바이트 변경 없음.
- JARVIS `64715bade176f5724bc4ebe8a40bc6f4c8f49a96` 그대로. 제출 source 동일, dist **1,216개**, 재사용 runtime **5,787개** SHA가 이전 069aeaa와 일치. dist digest `sha256:c64cfbf1c57f469927a453b1784b05508e33c9186f656a6546de86226e6aff36`; runtime lock/source lock 동일, launcher SHA `b3742f4e511c651b515aaff67a3df069f0cdd60afd5d20862ad49ea4fe9700ce` 동일. 작업 리포에서 이전 archive와 다른 tracked 파일은 **AGENTS.md만**이며 제품 바이트 변경으로 세지 않는다.
- **JARVIS 새 테스트/빌드/launcher 실행 0**. `/var/tmp/codex-night-069aeaa-080q44i1`의 실제 J10/dispatch3/build/launcher/consumer·정정 재선택 증거를 원 실행 핀과 함께 보존한다. 구dist를 새 SB 증거로 바꾸지 않았다.
- 원본 `/var/tmp/codex-night-ede1c1c-ac33gmxd`: archive, `identity.json`, `runtime-files.json`, `post-source-check.json`, `harness-sha256.json`, 명령별 로그/argv/cwd/시간 JSON, 문서 스냅샷. 이전 원본은 변경하지 않았다.

## 직접 실행

| 검사 | 결과 | 원본 |
|---|---|---|
| SB hook 정상 13개 | **13 passed / 1 deselected / 4.05s** | sb-tests.log/json |
| 변경 파일 Ruff | EXIT0 | sb-ruff.log/json |
| 변경 파일 타입 | **0 errors / 12 warnings / EXIT1** | sb-types.log/json |
| 설치 hook / 정상 원문 정정 / 인용 연결 | 아래 사례별 관측 | probe-sb.py, probe-correction.py, probe-followup.py 및 JSON/log |

자체 14pass 주장을 직접 결과로 쓰지 않는다. `test_session_state_uses_state_root_not_generation`은 수동 chmod helper fixture여서 이번 선택 검사에서 제외하고 **실제 정상 managed pipeline→설치 hook 경로**로 상태 분리를 확인했다. 그 helper를 콘텐츠 안내의 원인이라고 추정하지 않는다. 그 외 보류 검사는 실행하지 않았다. 타입 EXIT1은 완전 통과가 아니다. 이전 전체86/DR/성능/동일 JARVIS 회귀는 반복하지 않았고 probe를 pytest 성공 수에 합산하지 않는다.

## N2a — 목표 본문·record·인용 연결 확인

일반 Vault.write_pages로 만든 두 인용 페이지를 설치 CLI로 조회했다. query `OmegaUniqueTarget`에서 이제 다음 값이 함께 출력된다.

- 본문 `OmegaUniqueTarget actual second memory.`
- 출처 `fixture:omega.md`
- record_id `sbrecord:v1:c4928195809c3b377fd314801097613dd16f9717390b9013ebf68256376231bd`
- version `sha256:c4928195809c3b377fd314801097613dd16f9717390b9013ebf68256376231bd`

Alpha 본문/식별자가 이 문맥에 없다. `followup-probe.json`의 multi_*와 실제 committed record 바이트 비교가 판정 근거다. 단일 인용도 실제 record digest와 일치한다(`sb-identity-probe.json`). 임의 첫 record에 전체 snippet을 붙이던 결함은 이 범위에서 해결됐다.

초기 plain-vault harness가 명시한 새 registry 경로는 `_seed/stamp_knowledge`가 등록한 `.sb/knowledge-registry.sqlite`와 달랐다. 초기 빈 결과와 identity probe IndexError는 **검토 harness 오류**다. `.initial` 로그를 보존하고 같은 합성 fixture의 실제 등록 registry로 경로를 바로잡았다. 이 초기 결과를 제품 실패/성공 수로 세지 않았다. 정상 managed pipeline의 명시 config는 이 오류와 무관하다.

## N2b — 정상 managed 상태 저장은 해결, 출처는 여전히 손실

새 합성 source/vault/share/state/request/registry를 지정해 Alpha 원문→실제 run_ingest/run_compile→Omega 원문 정정→동일 pipeline을 실행했다. LLM 응답만 정상 본문을 만드는 합성 응답이다. 양쪽 ingest/compile EXIT0, 설치 PostCompact와 UserPromptSubmit도 EXIT0이다. 새 세대의 Omega 본문/새 record가 출력되고 Alpha query는 no_data다. stage는 **config.state_root/.sb/session-memory**에 기록되고 delivered:true, 동일 prompt/동일 c2 이벤트 재전달 뒤 출력은 `{}`다. generation 제자리 수정/chmod를 하지 않았다. `correction-probe.json:corrections`, `followup-probe.json:managed_*` 참조.

다만 Alpha와 Omega의 최종 문맥은 모두 **`source_ref=`가 비어 있다.** committed 실제 페이지에는 `origin: docs:note.md`와 정상 인용 정의가 존재한다. `followup-probe.json:source_binding`은 다음을 함께 기록한다.

- 검색 page_id: `wiki/docs-note-87c681b2`
- 실제 compile frontmatter id: `docs-note-87c681b2`
- `read_page_spec(root, 'wiki/docs-note-87c681b2')` 결과: None
- 실제 committed 원문 및 정상 cite origin `docs:note.md`

`sb/postcompact_hook.py:177–200`의 출처 연결은 `read_page_spec`에 의존한다. 이 helper는 `sb/vault.py:333–334`에서 stored_id와 전달 page_id의 동일성을 요구한다. 직접 만든 PageSpec fixture의 `wiki/...` id와 **정상 compile이 만드는 bare id**가 달라 spec이 None이고 빈 hit.source_ref가 그대로 나간다. 본문/record digest가 맞더라도 원 출처 보존 계약은 미충족이다.

완료조건: 정상 compile의 page 식별자 표현과 실제 인용 출처를 일관되게 해석해 **설치 hook 최종 문맥에 `docs:note.md`와 해당 최신 record를 함께** 보존한다. 정상 원문 저장/정정과 두 인용 페이지를 함께 확인한다. 빈 출처를 임의 문자열로 채우거나 record와 다른 첫 cite로 대체하지 않는다. 성공한 state 분리·확인·재전달·예산을 보존한다. 봉인 세대 수정/chmod·보류 검사를 의뢰하지 않는다.

## 예산·일반 실패·N3 보존

수정된 합성 harness의 stdout BrokenPipe EXIT1 후 설치 CLI 정상 재시도에서 문맥 재출력을 확인했다. 긴 요약과 no_data는 유지됐고, 별도 helper 최종 JSON 예산 probe는 3records/12,605bytes였다. 동일 session/prompt의 명시 c1→c2는 새 문맥, 같은 전달은 중복 처리됐다. 이는 제공된 ID의 정상 범위이며 native ACK/exactly-once나 ID 없는 이벤트 구분을 증명하지 않는다. JARVIS의 동일 범위는 앞의 동일 바이트 근거로 원 069aeaa 증거를 보존한다.

## N4 — 읽기 전용 문서 개선·잔여

현재 JARVIS 명령 핀64715ba, 실제 AUTH_DB, PATH 기반 sb run의 차이, 요청 writer/refresh 설명, 새 session state 경로, restore의 archive/to 피연산자 추가는 개선됐다. **운영·restore·rollback·writer 배제 검사를 실행한 것은 아니다.** 다음은 공개 소스/문서 정합성 문제다.

1. 운영 문서:20은 `request_root=$state_root/requests`라고 단정한다. `sb/config.py:176,269–271`에서 request_root를 생략하면 **DEFAULT_STATE_ROOT/requests** 상수이며, 설정으로 state_root만 바꿔도 그 값을 따라가지 않는다. 사용자 지정 state_root와 request_root는 각 값을 명시·해결하도록 표를 고쳐야 한다. :23은 generation locks가 generation.json과 같은 위치라고 하지만 `sb/generations.py:595`의 lock_path는 **state_root/generation.lock**, writer lock도 같은 state_root다. generation metadata와 혼동하지 않아야 한다.
2. :33은 refresh.timer를 관측하지만 :35의 stop 대상은 서비스뿐이다. 기존 공개 `deploy/systemd/second-brain.timer` 등 예약 writer의 재기동 방지와 서비스 정지를 구분해야 한다. stop 후 JARVIS DB handles만으로 SB writer/lock·pending/lease 조건을 대신하지 않는다. 기존 도구의 `drain_authorized:false` 한계와 정본의 SB run.lock/세대 writer 조건을 읽기 자료에 연결한다. 실제 현재 timer/프로세스 상태는 이번에 조회하지 않았다.
3. :37의 두 current 변경 중 **SB 성공→JARVIS 실패**를 :49의 “이전 current 유지/새 current 없음”으로 설명할 수 없다. 이 문장은 명백히 부분 전환 상태를 누락한다. 각 링크 미변경/새 후보/확인 불가 상태를 기록하고 **둘 다 승인된 새 후보로 정합화되기 전 모든 writer 기동 금지**, 구버전 자동 복귀 금지라는 기존 제약 아래 다음 행동을 정해야 한다. 이는 문서 작성 조건이지 부분 전환·복원 실험 의뢰가 아니다.
4. 후보 변수는 이미 알려진 `/var/tmp/sb-candidate-b9844ef/releases/3ae0a9a4c6db8934a814298f2ee741acc15c8349`와 `/var/tmp/jarvis-artifact-64715ba`로 구체화할 수 있다. 실제 링크 명령 피연산자/서비스 기동 명령 및 합의 config 연결을 각각 적고, 실제 외부 값인 archive/to/당일 PID/hash만 이름 있는 슬롯과 미충족 시 정지 조건으로 남긴다. :50의 격리 복원 뒤 “같은 새 릴리스 start”는 복원된 경로와 서비스 config의 연결/검증 전 중단 조건이 빠져 있으므로 기존 상세 자료의 제약을 링크해 완성한다. 보류된 복원 수명 통과를 전제로 쓰지 않는다.

한 번의 **읽기 전용 N4 정합화**로 위 표·변수·단계별 상태를 함께 고친다. 새로운 운영 도구/권한/기능을 만드는 의뢰가 아니다. 운영 실행/실config·auth 복사/보류 검증은 계속 하지 않는다.

## 보존·외부 조건·후속 범위

N1의 다음 UserPromptSubmit은 자동 compaction 직후 같은 turn의 다음 모델 요청과 다르다. 공개/native 한계는 새 구현 의뢰로 바꾸지 않고 미완료로 유지한다. 실제 selected task/원문·공유 대상, 격리 native 프로필/consumer 구성, 실사용 한글 gold/자료 크기·지연 목표, 운영 중단·전환·백업·timer 허가 및 RPO/RTO가 외부 조건이다. 입력 없이 가능한 정상 **출처 연결 수정과 N4 문서**는 기존 Grok에 통합 전달한다.

과거 M11 정상 정정/worker, 검색/MCP/DR/원장 retry 등은 원 핀·진입점·로그의 한정 증거로 보존한다. 원 A–F/M1–M14 전체 미완료이며 이번 정상 검사로 보류 수명을 닫지 않는다. 콘텐츠 안내 발생 검사는 원인 미확정, 관련 보안/삭제/경합/복원 수명 재시도·수정·다른 모델/도구/세션/Grok 이전 없음. 제품 소스 수정/운영 전환/auth/config 복사/실사용자 삭제/push/새 작업·모델·주기 변경 없음. root 소유 control/야간보고에 동시 쓰지 않고 본 보고서와 증거 상태만 작성했다.

직접 전달과 공식 목표 재개, 실제 수신·도구 착수·지속 관측을 아래에 별도 기록한다.

## 직접 전달·공식 재개 관측

기존 Grok `term_dc97574f3e548cff6e25679d713ed8c2`에 본 통합 문서와 한정 완료조건을 직접 전달했고 accepted:true를 받았다. 직후 화면6074142는 Goal achieved였다. 공식 `/goal resume` accepted:true 뒤 **화면6074216에서 Goal active/Pursuing goal** 및 본 MD:1–120 읽기를 확인했다. 이어 `sb/vault.py:310–339` 읽기까지 관측해 ACK/실제 수신·도구 착수/소스 조사 지속을 구분했다. 제품 수정 완료나 다음 후보 인수는 아직 관측하지 않았다. 내부 thinking은 보고하지 않는다.

기존 자동화 읽기 관측은 enabled:true, Asia/Seoul이다. 30분 주기를 포함한 설정을 변경하지 않았다. 원본 메시지/ACK/screen은 증거 루트에 보존하며 root 소유 control/야간보고에는 동시 쓰지 않았다.
