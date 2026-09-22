# 고정 제출 b87fba7 독립 검토

작성자: **기존 지정 감시 Codex `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`**. 작성 시각 2026-09-13T08:39:43.812218+00:00. 원래 Codex는 조정만 수행했으며 아래 직접 검사는 본 작업의 실행이다.

**판정: 출처 복구는 확인했으나 정상 compile record ID·버전의 회귀와 N4 문서 잔여로 일반 인수 미통과. 전체 제품/운영 인수 미완료.** completion/remaining-triage/progress-control과 원 A–F/M1–M14를 유지한다. 콘텐츠 안내 후 일반 범위 계속은 원래 Codex의 조정 결정이며 사용자 목표 축소가 아니다.

## 고정·실행 출처

- 제출 `b87fba782f1c26fbd0ce77b9550615f65b2e91ea`, SB source `7cc5fbc803451b24066546563b63b25f266a4998`.
- 후보 `/var/tmp/sb-candidate-7cc5fbc/releases/99746496b854f6fb42b69466bebca58149bb9396`. wheel SHA256 `b46f487973d11ca4cc8e80d749e0a50eac524a65972d22432f7d1da8682a5578`.
- 독립 archive SHA256 `3a4a1a10ef61e9217f60b2dd63d33e1041eb82eef83237befa2053b6c5e93d32`. **183개 SB Python source/wheel/installed 파일 일치**. 종료 HEAD 동일, 제품 tracked diff 없음, source/tests/scripts/deploy/systemd 617개 바이트 동일.
- JARVIS `64715bade176f5724bc4ebe8a40bc6f4c8f49a96`: artifact source 일치, dist 1,216개 및 runtime 5,787개가 원 069aeaa 증거와 동일. dist digest `sha256:c64cfbf1c57f469927a453b1784b05508e33c9186f656a6546de86226e6aff36`; runtime lock/source lock 동일. launcher SHA256 `b3742f4e511c651b515aaff67a3df069f0cdd60afd5d20862ad49ea4fe9700ce`. 실제 작업 리포의 이전 archive 대비 차이는 AGENTS.md만이며 제품 차이가 아니다.
- **JARVIS 새 검사/빌드/launcher 실행 0**. `/var/tmp/codex-night-069aeaa-080q44i1`의 consumer·정정/명시 dispatch·실행 artifact 증거를 해당 핀으로 보존한다.
- 원본 증거: `/var/tmp/codex-night-b87fba7-hpq53ygw`. `identity.json`, `runtime-files.json`, `post-source-check.json`, `harness-sha256.json`, archive와 문서 스냅샷, 아래 명령별 argv/cwd/exit/시간/원본 출력. 이전 원본을 변경하지 않았다.

## 직접 실행과 한계

| 검사 | 직접 결과 | 원본 |
|---|---|---|
| 고정 source hook 정상 선택 회귀 | **14 passed, 1 deselected / 3.73s**, EXIT0 | sb-tests.log/json |
| 변경 hook/CLI/test Ruff | EXIT0 | sb-ruff.log/json |
| 같은 파일 타입 | **0 errors, 12 warnings, EXIT1** | sb-types.log/json |
| 정상 managed 원문 저장·정정→pipeline→설치 hook | 출처/본문 회복, 원 record 식별자·digest 불일치 | correction-probe.json/log, followup-probe.json/log, record-contract-probe.json/log |
| 단일·다중 인용 및 명시 c1→c2 | 아래 범위 통과 | sb-identity-probe.json/log, followup-probe.json/log |

Grok 자체 15pass 주장은 직접 실행 수가 아니다. 수동 chmod fixture `test_session_state_uses_state_root_not_generation`은 선택에서 제외하고 정상 managed pipeline을 통해 상태 분리를 관측했다. 그 fixture가 콘텐츠 안내 원인이라고 추정하지 않는다. 타입 EXIT1은 완전 통과로 쓰지 않는다. 전체/DR/성능/보류 검사와 같은 JARVIS 검사를 반복하지 않았다. probe 사례를 pytest 개수에 합산하지 않는다.

`probe-sb.py`는 결과 수집 마지막에 옛 `probe-state` 경로를 읽어 StopIteration으로 종료했다(실제 fixture는 `probe-state-fixed`). **검토 harness 오류**이며 제품 실패로 세지 않는다. sb-probe.json은 생성되지 않았으므로 이 실행을 stdout 재시도/긴 요약/예산의 새 성공 증거로 삼지 않는다. 해당 기존 통과는 원 ede1c1c/069aeaa 로그와 변경 영향 범위로 보존한다. 독립적으로 완료된 correction/identity/followup/record-contract 증거는 이 수집 오류와 무관하다.

## N2 — 출처 수정이 원 record 식별자를 바꾼 회귀

합성 source `docs:note.md`에 Alpha 원문 저장→실제 run_ingest/run_compile→Omega 본문 정정→동일 정상 pipeline으로 새 세대를 게시했다. LLM 생성 응답만 합성 정상 본문이다. 봉인 세대 제자리 수정/chmod 없이, 설치 후보의 PostCompact→UserPromptSubmit stdout을 관측했다. 두 시점 모두 올바른 본문과 **source_ref=docs:note.md**가 출력된다. 이전 빈 출처 문제는 이 범위에서 해결됐다.

그러나 최종 record ID/version은 같은 committed generation의 기존 provider record와 다르다.

| 시점 | 원 provider record ID의 digest 부분 | 설치 hook record ID/version의 digest 부분 |
|---|---|---|
| Alpha | 12320554dcba04a58d4376d79938ca354857890ac2eadd9dbfbf5f83918656cb | a000eff4d705b8028fabf6a21e45839017f0528a790332c79cd0e21ccda572b8 |
| Omega | be694b53c381091018793c78e0b4f7a0fa6f74b16ac9206c18aa3e7b9fe54408 | e98193dd19a8248189b357f4979a5e3f825ddc8bac0b3f237709d918c3c665d6 |

`record-contract-probe.json`는 실제 committed Omega generation에 **기존 `records_for_page(root, 'wiki/docs-note-87c681b2', generation)`**를 적용한 결과와 설치 hook 저장 record를 대조해 `same_record_id:false`, `same_record_digest:false`를 기록한다. 이는 실제 MCP search/read가 쓰는 provider 함수의 직접 비교이며 **live MCP 클라이언트/로그인/native 실행이 아니다**. `sb/mcp.py:581,614`는 검색·read의 canonical wiki page_id를 그대로 전달한다.

원인 위치: `sb/postcompact_hook.py:223–225`가 metadata 조회로 찾은 bare `spec.page_id`를 `parse_page_records`에 넣는다. `sb/memory_records.py`의 citation identity는 page_id를 포함하므로 원 provider의 wiki 경로와 다른 ID/digest가 생성된다. `tests/test_postcompact_hook.py:340`의 기대값 역시 bare id로 재계산해 이 회귀를 놓친다. 출처 lookup alias와 **원 record identity**를 혼동했다.

완료조건: bare frontmatter와 wiki/path를 출처 metadata 조회에서 정상 대응시키되 **기존 provider canonical record ID/digest를 최종 설치 hook까지 그대로 보존**한다. 정상 managed Alpha→Omega 양쪽에서 실제 provider record를 기준으로 본문/ID/digest/출처를 동시에 비교하고 구본문 제외를 확인한다. 두 인용 페이지도 같은 기준으로 검증한다. 기대값을 새 bare id로 재계산하거나 기존 전체 record identity를 바꾸어 문제를 덮지 않는다. 보류 검사/운영 인증은 이 수정에 필요하지 않다.

보존 통과: 다중 인용 `OmegaUniqueTarget`은 `fixture:omega.md` 및 원 record `sbrecord:v1:c4928195809c3b377fd314801097613dd16f9717390b9013ebf68256376231bd`와 연결되고 Alpha를 포함하지 않는다. 단일 seed도 원 digest와 동일하다. managed state는 mutable state_root에 분리되고 delivered:true, 동일 prompt 및 c2 재전달 뒤 `{}`, 이전 Alpha query no_data `{}`를 확인했다. 같은 prompt의 명시 c1→c2는 각 새 문맥을 출력한다. ID 없는 native occurrence나 native ACK/exactly-once를 증명하지 않는다.

## N4 — 읽기 전용 정합화의 개선과 잔여

현재 운영 문서에서 request_root가 사용자 state_root를 자동 추종하지 않는다는 수정, state_root의 generation.lock/generation-writer.lock 위치, refresh.timer 정지, SB 성공/J 실패 부분 상태와 start 금지, 구버전 start 금지는 개선됐다. 아래는 **문서와 공개 소스 비교**이며 운영/restore/rollback/lock 배제 검사를 실행한 결과가 아니다.

1. `GROK-CURRENT-OPERATIONS-REVIEW-2026-09-13.md:30–35`: stop 목록에 second-brain.service는 있지만 공개 `deploy/systemd/second-brain.timer`(hourly/Persistent)가 빠졌다. 공개 `systemd/user/jm-second-brain-requests.path`도 requests.service를 재활성화한다. 현재 활성이라고 추정하지 않으며, 사용 중인지 확인할 대상과 사용 시 정지·재활성화 배제 조건을 적어야 한다. DB handles만으로 SB writer를 제외할 수 없다. `sb/pipeline.py:148`의 **실제 실행 root/.sb/run.lock**(managed 실행은 staging root)과 state_root의 세대 locks를 구분해 각 경로/상태를 연결한다. pending/lease는 단순 “관측”이 아닌 충족/미충족 시 행동이 필요하고 `drain_authorized:false`를 승인으로 해석하지 않는다. 이는 읽기 자료 완성 조건이며 실제 drain/lock/경합 실행 의뢰가 아니다.
2. :39–48의 `<SB후보절대경로>/<J후보절대경로>`는 이미 알려진 후보와 연결할 수 있다. SB=`/var/tmp/sb-candidate-7cc5fbc/releases/99746496b854f6fb42b69466bebca58149bb9396`, J=`/var/tmp/jarvis-artifact-64715ba`. `SB_CURRENT/bin/sb` 자체는 서비스 기동 명령이 아니다. 공개 service/config 기준 실제 subcommand/필수 인자/config 소비 위치 및 PATH 기반 유닛과 current 기반 유닛의 차이를 표로 완성한다. 사용자 확인이 필요한 config 값만 이름 있는 슬롯으로 남긴다.
3. :44,50의 부분 전환과 격리 restore 후 다음 행동: 링크별 미변경/새 후보/확인 불가 상태를 명시하고 **합의 핀·config 검증 전 모든 writer 정지 유지**, 구버전 자동 복귀 금지를 일관되게 적용한다. “restore 후 같은 새 릴리스 start”는 복원된 경로와 서비스/config의 연결 및 검증 전 중단 조건이 빠져 있다. 필요한 archive/to/config 매핑·확인 결과물과 실패 단계별 정지 상태를 기존 정본에 연결해 문서로 준비한다. 실제 복원 실행/성공/수명 인수를 요구하거나 가정하지 않는다.

위 N2 정상 수정과 N4 문서 잔여를 하나의 후속으로 처리한다. 새 기능/운영 도구/승인 범위를 추가하지 않는다.

## 원 요구·보류·외부 조건

N1에서 다음 UserPromptSubmit과 자동 compaction 직후 같은 turn의 다음 모델 요청은 서로 다르다. 공개/native 제약은 새 의뢰로 만들거나 전체 M9 완료로 바꾸지 않는다. 원 A–F/M1–M14와 앞선 triage의 미완료를 유지하며 과거 M11/MCP/DR/원장 retry는 원 실행 핀·경로·로그에 한정한다.

실제 사용자 task/원문·공유 대상, 격리 native 프로필과 consumer 구성, 실사용 한글 gold/자료 크기·지연 목표, 운영 중단/전환/백업/예약 writer 허가 및 RPO/RTO는 외부 조건이다. 입력 전에 준비 가능한 정상 N2 수정과 N4 문서는 외부 차단으로 재분류하지 않는다.

콘텐츠 안내의 정확한 발생 검사/원인은 미확정이다. 관련 보안/삭제/경합/복원 수명은 **보류·미검증**이며 재시도/수정/다른 도구·모델·세션·Grok 이전 없음. 이 정상 검증으로 보류 범위를 닫지 않았다. 제품 소스 수정/운영 전환/auth·config 복사/실사용자 삭제/push/새 작업·모델·주기 변경 없음. root 소유 control/야간보고에 동시 쓰지 않고 본 검토와 증거 상태만 작성했다.

## 직접 전달·공식 목표 재개

기존 Grok `term_dc97574f3e548cff6e25679d713ed8c2`에 위 단일 통합 문서를 직접 전달해 accepted:true를 받았다. 직후 화면6076550은 Goal achieved였고, 공식 `/goal resume`도 accepted:true였다. 화면6076569에서 Goal active/Pursuing goal, **화면6076664에서 본 MD:1–100 실제 읽기와 `sb/postcompact_hook.py:200–249` 조사**를 확인했다. 전달 ACK, 실제 수신·도구 착수, 다음 소스 조사 진행을 구분한다. 수정 완료/다음 후보 인수는 아직 관측하지 않았다. 내부 thinking은 보고하지 않는다.

자동화 읽기 결과 enabled:true/Asia/Seoul을 확인했고 기존 30분 설정은 변경하지 않았다. 원본 메시지/ACK/screen을 증거 루트에 보존했다. control JSON/야간보고에는 동시 쓰지 않았다.
