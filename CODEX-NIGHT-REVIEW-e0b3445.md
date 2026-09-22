# 고정 제출 e0b3445 독립 검토

작성자: **기존 지정 감시 Codex `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`**. 2026-09-13T09:07:46.193376+00:00. 조정 Codex가 중복 실행한 결과가 아니다.

**판정: b87fba7의 N2 정상 record 연결 회귀 해결. N4 출처/운영 준비 문서 잔여로 통합 인수 미완료. 이번 정상 구현에서 새 제품 결함은 확인하지 않았다.** 다음 후속은 문서 정합화이며 제품 수정이나 운영 실행을 요구하지 않는다. 원 A–F/M1–M14, completion/triage/progress-control의 전체 미완료와 보류를 유지한다.

## 핀·바이트·검사 출처

- 제출/검토 테스트 핀: `e0b3445a49164ab7d4606b15d828581d29e6a2e1`.
- 제품 핀: `a41b70dd165dda265fdc7d2b84df0da8d9fb9fb2`.
- 후보: `/var/tmp/sb-candidate-a41b70d/releases/c9bdc5dd520b0e3908207cf34f319799e48bb19a`.
- wheel SHA256: `dc1be265f1c4eee10bda26e960ec085d2e7f83c052fd6b405c9c8656926c5fb0`. 제품 핀 archive/wheel/installed/검토 HEAD의 **183개 SB Python 파일 일치**.
- 독립 제품 archive SHA256 `c811d67212c112f7759a7901cdab95a34788d2d80d5d23cd6ea50a8a0fe18cba`; 검토 HEAD archive SHA256 `295b81fdf8b755f5646460ddd67b232b773bf71c4ee7e3027bfbb650357a6b33`.
- `tests/test_postcompact_hook.py` SHA256는 제품 archive `61d300f46f35627d85ed5b152bd85d5fb56abe2adbe7b782cf9752823afb7e47`, 최신 검토 archive `5c3022574a4a621df8477f50a0ae5320d4425fc22c05058f0950198b598b3db8`. **이번 pytest는 최신 e0b3445 테스트를 실행했다.** 옛 archive 테스트를 최신이라고 바꾸지 않았다. release-manifest의 source=a41b70d, working_tree_modified:true도 실제 기록대로 보존한다.
- 종료 HEAD 동일, 제품/tests/scripts/deploy/systemd tracked diff 없음, 617파일 고정 바이트 일치. root 소유 control JSON 변경은 제품 변경으로 세거나 덮어쓰지 않았다.
- 원본 `/var/tmp/codex-night-e0b3445-f2vx7crf`: 두 archive와 독립 복사본, `identity.json`, `post-source-check.json`, `harness-sha256.json`, 명령별 로그/JSON 및 아래 probe. 이전 원본은 보존했다.

JARVIS는 `64715bade176f5724bc4ebe8a40bc6f4c8f49a96`. 제출 source가 이전 고정 source와 일치하고 **backend manifest 1,216개 엔트리의 실제 SHA와 이전 rebuild 엔트리가 모두 동일**하다. digest `sha256:c64cfbf1c57f469927a453b1784b05508e33c9186f656a6546de86226e6aff36`. runtime 5,787파일과 launcher SHA `b3742f4e511c651b515aaff67a3df069f0cdd60afd5d20862ad49ea4fe9700ce`도 이전 바이트와 일치한다.

backend manifest 범위와 전체 디렉터리를 구분했다. 제출 dist의 파일 탐색은 1,222개이며 manifest 밖에 build-metadata, build-lock DB 및 dashboard 네 파일이 있다. 독립 backend rebuild와 전체 디렉터리를 비교하면 dashboard/metadata 차이가 나타나지만 **backend 엔트리 불일치는 0**이다. 이를 새 J 제품 회귀로 세지 않으며 dashboard 인수를 이번에 확장하지 않는다. J 새 빌드/테스트/launcher 실행은 **0**. `/var/tmp/codex-night-069aeaa-080q44i1`의 consumer/dispatch/artifact 검증을 원 핀·실행 경로에 한정해 보존한다.

## 직접 실행

| 검사 | 직접 결과 | 원본 |
|---|---|---|
| 최신 테스트 파일 전체 정상 hook 회귀 | **15 passed / 1.38s**, EXIT0 | sb-tests.log/json |
| 변경 hook/CLI/test Ruff | EXIT0 | sb-ruff.log/json |
| 같은 파일 타입 | **0 errors / 12 warnings / EXIT1** | sb-types.log/json |
| 정상 pipeline→설치 hook 및 provider 비교 | 아래 N2 통과 | correction-probe, provider-correction-probe, record-contract-probe, followup-probe의 json/log |

이번 15는 직접 실행 수이며 인계의 자체 15와 별개다. e0b3445의 session state 테스트는 chmod가 제거된 일반 상태 저장 assertion으로 확인 후 실행했다. 이 사실은 보류된 경계 검사가 통과했다는 뜻이 아니다. 과거 14/86/DR/성능과 합산하지 않는다. 타입 EXIT1은 완전 통과로 표기하지 않는다. probe는 pytest 수치에 더하지 않았다.

## N2 — 원 provider identity와 출처의 정상 연결 통과

제품 `sb/postcompact_hook.py:224`가 canonical 검색 `hit.page_id`로 parse하고, bare metadata id는 `_spec_for`의 출처 조회 alias로만 사용한다. 이 분리로 이전 회귀가 해결됐다.

1. 새 합성 managed source에서 Alpha 저장→실제 run_ingest/run_compile→Omega 정상 원문 정정→동일 pipeline의 새 세대 게시를 실행했다. LLM generate만 정상 본문을 만드는 합성 응답이다. 각 시점의 실제 verified generation에 `records_for_page`를 직접 호출하고 **설치 후보 CLI PostCompact→UserPromptSubmit 최종 출력의 본문/ID/digest/출처를 동시에** 대조했다. provider-correction-probe의 두 단계 모두 네 assertion이 true다. Alpha와 Omega 원 record ID는 각각 `sbrecord:v1:12320554dcba04a58d4376d79938ca354857890ac2eadd9dbfbf5f83918656cb`, `sbrecord:v1:be694b53c381091018793c78e0b4f7a0fa6f74b16ac9206c18aa3e7b9fe54408`이고, 최종 hook이 같은 ID와 digest·`docs:note.md`를 보존한다. Omega 문맥에는 Alpha 본문이 없다.
2. 일반 Vault.write_pages의 두 인용 페이지에서 Omega 목표만 선택하며 `fixture:omega.md`, 원 record ID/digest `c4928195809c3b377fd314801097613dd16f9717390b9013ebf68256376231bd`와 일치한다. Alpha 인용 본문은 최종 문맥에서 제외된다. bare page id와 다중 인용을 함께 다루는 최신 제품 테스트도 통과했다.
3. managed mutable state_root 분리, delivered:true, 동일 prompt와 c2 재전달의 빈 출력, 이전 Alpha query의 no_data를 별도 설치 CLI 관측으로 확인했다. `assertion-summary.json`의 아홉 조건이 true다.

처음 correction probe는 committed canonical parser 비교와 설치 hook, 두 번째 provider-correction probe는 **각 세대가 교체되기 전에 실제 provider 함수 비교**를 기록했다. 서로 다른 synthetic fixture이며 후자를 새 pytest 개수로 세지 않는다. 과거 probe-sb 수집 경로 오류를 복제·재실행하지 않았다.

검증 경계는 합성 정상 원문과 실제 pipeline/설치 hook 및 provider derivation 함수다. **live MCP 클라이언트·로그인 native·실모델 요청을 실행한 것이 아니다.** 변경 없는 정상 stdout 재시도/최종 예산/긴 요약/no_data/명시 occurrence는 관련 15회귀와 원 핀의 기존 로그에 한정해 보존한다. N1의 다음 UserPromptSubmit은 auto-compaction 직후 같은 turn의 다음 모델 요청을 대체하지 않는다.

## N4 — 개선과 남은 필수 문서 정합화

운영·restore·rollback·lock 실험 없이 공개 파일/문서만 읽었다. 개선된 항목: timer/path와 서비스의 정지 대상을 함께 기재, 실제 실행 root의 run.lock과 state_root 세대 locks 구분, 양방향 부분 전환의 start 금지, 격리 restore 후 config 명시·검증 전 writer 정지, 구버전 start 금지. 이를 다시 미구현이라고 하지 않는다.

남은 것은 다음 한 묶음의 **문서 수정**이다.

- **현재 핀:** `GROK-CURRENT-OPERATIONS-REVIEW-2026-09-13.md:9`는 아직 7cc5fbc 후보를 현재 후보로 표시한다. 인계 a41b70d와 모순이다. 위의 실제 c9bdc5d release를 후보 변수/링크 피연산자에 연결하고, product=a41b70d / test=e0b3445 / 자체 로그 실행 핀을 각각 분리한다. `<J후보/authority release>`도 J runtime 후보와 운영 authority/current의 관계를 분명히 적는다.
- **unit 출처·실행/config 연결:** :29–30의 공개 activator 표는 리포 템플릿과 다르다. `systemd/user/jm-second-brain-requests.path:5`는 **PathChanged**이며 문서의 DirectoryNotEmpty/ConditionPathExists가 없다. service:3,7은 ConditionPathIsDirectory와 `/usr/bin/env sb apply-requests --once`이지 current 절대 경로가 아니다. “pending 비면”도 비어 있을 때인지 명확히 바로잡는다. 만약 설치 unit을 설명한 것이라면 관측 시각·정확한 공개 unit 출처를 붙여 **리포 예시/설치 관측/제안 설정을 분리**한다. 이번 검토는 설치 unit이 이렇다고 주장하지 않는다. `deploy/systemd/second-brain.service:9–12`의 SB_CONFIG/PATH 소비와 실제 새 후보로 기동할 경로/config의 차이를 숨기지 않는다. :64의 “새 current 절대 경로만” 및 인자 없는 search 예시는 준비된 기동 절차를 대신하지 않으므로 기존 정상 subcommand/필수 인자/config 소비 위치를 명시한다. 운영에 적용하지 않는다.
- **사후조건·복구 전 중단:** :49는 여전히 pending-state “관측”만 있고 pending/active cursor/unexpired 또는 invalid lease가 남는 경우 판단이 없다. `deploy/check-jarvis-pending-state.py`의 EXIT0·집계가 허가가 아님을 보존하고, 미해결/미확정이면 **current 변경 및 writer 기동 금지·정지 유지·필요 입력 기록**, 임의 drain/expiry/구버전 복귀 금지를 명시하면 된다. :61의 config 필드 이름을 넘어 격리 restored root와 검증 명령이 소비할 config 경로, 검증 전/실패 시 정지, 검증 성공도 실제 운영 기동 승인과 별개라는 매핑을 문서로 준비한다. archive/to/실config 값은 외부 슬롯으로 남겨도 되며 새로운 실제 복원·lock·보류 시험은 필요 없다.

완료조건은 위 세 항목을 최신 고정 후보와 공개 근거에 맞춰 **한 번에 문서 정합화**하는 것이다. N2 정상 코드를 다시 고치거나 동일 회귀 전체를 반복할 이유는 없다. 단순 문구 다듬기가 아니라 이전 후보 실행과 확인되지 않은 writer 재기동 판단을 막기 위한 원 N4 잔여다.

## 보존·외부 입력·전체 미완료

원 A–F/M1–M14를 정상 N2/N4로 축소하지 않는다. 제한 안내 뒤 정상 범위 계속은 원래 Codex의 조정이며 사용자 목표 변경이 아니다. 정확한 콘텐츠 안내 원인은 미확정, 관련 보안/삭제/경합/복원 수명은 보류·미검증이며 재시도·수정·타 도구/모델/세션/Grok 이전하지 않았다. 정상 연결 통과로 그 수명을 닫지 않는다.

외부 조건은 실제 사용자 task/원문·공유 대상, 격리 native 프로필/consumer 구성, 실사용 한글 gold·자료 크기·지연 기준, 운영 중단/전환/백업/예약 writer 허가와 RPO/RTO 및 당일 config/archive/to 값이다. N1 native/in-turn 한계도 그대로 남으며 새 의뢰로 바꾸지 않는다. 과거 M11/MCP/DR/원장 retry는 원 핀·경로의 증거로 보존한다.

제품 수정/운영 전환/auth·config 복사/실사용자 삭제/push/새 작업·모델·주기 변경 없음. TMPDIR=/var/tmp의 합성 fixture만 사용했다. root 소유 control/야간보고에는 쓰지 않고 본 검토와 증거 상태만 작성했다. 정상 N4 문서 후속만 기존 Grok에 전달하고 ACK/공식 재개/실제 착수를 따로 기록한다.

## 직접 전달·재개·실제 착수

기존 Grok에 본 단일 통합 검토서를 직접 전달해 accepted:true를 받았다. 직후 화면6078983은 Goal achieved였으며 공식 `/goal resume` accepted:true 후 화면6079002에서 Goal active/Pursuing goal을 확인했다. **화면6079195에서 본 MD/JSON 및 운영 문서를 실제로 읽고, 설치 request path/service의 공개 정의와 pending-state 검사기·리포 unit 근거 조사로 이어진 것**을 확인했다. ACK, 실제 수신·착수, 다음 문서 근거 조사 진행을 구분한다. N4 문서 완료나 다음 인수는 아직 관측하지 않았다. 내부 thinking은 보고하지 않는다.

자동화는 enabled:true/Asia/Seoul로 읽기 확인했고 기존 30분 주기·설정을 변경하지 않았다. 공유 control/야간보고에는 쓰지 않았다.
