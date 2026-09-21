# 문서 전용 고정 제출 e53dd66 독립 검토

작성자: **기존 지정 감시 Codex `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`**. 2026-09-13T09:36:42.457905+00:00. 조정 Codex의 중복 검토가 아니다.

**판정: N2 정상 통과 보존. N4 현재 핀/로그 분리는 해결됐으나 unit 설정의 사실 오류와 pending 판정·복원 후 config 소비 매핑 잔여로 문서 인수 미완료.** 제품 변경이나 새 제품 검증을 요구하지 않는다. 원 전체 제품/운영 인수도 미완료다.

## 고정과 기존 증거 보존

제출 `e53dd6653658d7b0a061dc1e8c65316c6c3f4268`. e0b3445 이후 tracked 변경은 운영 MD, 통합 인계 MD, client readiness JSON **세 문서뿐**이다. 제품 `a41b70dd165dda265fdc7d2b84df0da8d9fb9fb2`, 테스트 `e0b3445a49164ab7d4606b15d828581d29e6a2e1`를 별도로 유지한다.

- SB 후보 `/var/tmp/sb-candidate-a41b70d/releases/c9bdc5dd520b0e3908207cf34f319799e48bb19a`.
- wheel SHA256 `dc1be265f1c4eee10bda26e960ec085d2e7f83c052fd6b405c9c8656926c5fb0`. 실제 source/wheel/installed Python **183파일이 기존 제품 핀과 일치**.
- 테스트 SHA256 `5c3022574a4a621df8477f50a0ae5320d4425fc22c05058f0950198b598b3db8`는 e0b3445와 동일.
- JARVIS64715ba backend manifest 1,216개 실제 바이트 일치, digest `sha256:c64cfbf1c57f469927a453b1784b05508e33c9186f656a6546de86226e6aff36`. 기존 runtime 파일 SHA 일치, launcher SHA `b3742f4e511c651b515aaff67a3df069f0cdd60afd5d20862ad49ea4fe9700ce`. dashboard 등 manifest 밖 범위는 이전 검토와 같이 backend 검증에 포함하지 않는다.
- 원본 `/var/tmp/codex-night-e53dd66-o0p1mvne/identity.json` 및 세 제출 문서 스냅샷. 종료 핀과 문서 바이트도 고정 확인했다. root 소유 control JSON의 별도 변경은 건드리지 않는다.

**이번 테스트/회귀/build/launcher 실행 0.** `CODEX-NIGHT-REVIEW-e0b3445.md/.json`과 `/var/tmp/codex-night-e0b3445-f2vx7crf`의 N2 정상 managed Alpha→Omega provider 본문/ID/digest/출처와 설치 hook 일치, 구본문 제외, 다중 인용, 상태/중복 처리를 원 경로에 한정해 이어받는다. 이전 직접 15 passed/1.38s, Ruff EXIT0, 타입0errors/12warnings/EXIT1은 **과거 실행**이며 이번 실행 수치가 아니다. JARVIS consumer/dispatch 증거도 원069aeaa 핀·실행을 보존한다. live MCP/native 모델 요청이나 보류 수명 인수로 확장하지 않는다.

## 해결된 N4 범위

현재 SB 후보 c9bdc5dd/product a41b70d/test e0b3445와 과거 `sb-gates-f7c1945.log`의 구분은 MD/JSON 사이에 일치한다. J runtime과 authority current를 구분하고 authority release의 미확정 경로를 이름 있는 슬롯으로 남겼다. PathChanged와 DirectoryNotEmpty 개념, 리포/설치 관측 구획, timer/path와 서비스 정지 대상, 실제 root run.lock/세대 lock 구분, pending/lease 미해결이면 정지 유지·drain_authorized:false 한계, 부분 전환 start 금지, 복원 검증 성공과 운영 승인 구분은 개선됐다. 이 범위를 다시 결함으로 세지 않는다.

## 남은 문서 완료조건 — 한 번의 통합 후속

### D1. unit의 실제 config 소비와 제안 설정을 분리

`GROK-CURRENT-OPERATIONS-REVIEW-2026-09-13.md:40`의 requests.service 리포 표에는 `Environment=SB_CONFIG=%h/.config/second-brain/config.toml`이 실제 설정처럼 기재됐다. 그러나 고정 `systemd/user/jm-second-brain-requests.service:3,7–8`은 ConditionPathIsDirectory, `/usr/bin/env sb apply-requests --once`, NoNewPrivileges이고 **SB_CONFIG Environment 행이 없다**. 반면 `deploy/systemd/second-brain.service:9`에는 그 행이 있다. 서로 다른 유닛의 설정을 섞으면 안 된다.

완료조건: requests.service 리포에는 명시 SB_CONFIG 없음과 `sb/config.py:184–192`의 환경변수→user config→app fallback을 적고, 별도 제안 설정이 필요하면 proposed로만 표기한다. 설치 unit도 읽은 정확한 경로/관측 시점/관측 행과 미관측 활성 상태를 구분한다. shell용 변수 `SB_CONFIG=%h/...`(:23)는 systemd의 %h 치환과 다르므로 shell 예시에서는 알려진 `/home/jm/.config/second-brain/config.toml` 또는 명시된 검증 config 절대 경로를 쓴다. 실제 설정을 쓰거나 복사할 필요는 없다.

### D2. pending 집계의 모양과 중단 판정을 일치

운영 문서:64의 “pending states 비어 있지 않음”은 집계 객체의 비어 있음인지, 각 상태의 미해결 건수인지 불명확하다. `deploy/check-jarvis-pending-state.py:46–53`는 고정 테이블 이름을 키로 갖는 **states 객체**를 만든다. 모든 조회 결과가 빈 리스트여도 객체 자체는 비지 않으므로 그 표현만으로는 실행 가능한 판정이 아니다. 새 DB 조회/fixture 실행 없이 공개 구현을 읽어 확인했다.

완료조건: 집계의 각 table/state/count가 어떤 미해결 항목인지 판정 가능한 읽기 표 또는 명시적 “분류/완료 근거가 없으면 정지 유지” 규칙을 적는다. `{table: []}`와 잔여 count를 구분하고, active cursor·두 lease 종류의 unexpired/invalid·누락/미관측을 모두 중단 조건으로 연결한다. 이미 종료된 이력은 자동으로 미해결 pending이라 단정하지 않고, 근거 없으면 미확정으로 남긴다. EXIT0/빈 결과도 drain 허가나 운영 승인으로 쓰지 않는다. 임의 drain/만료 처리/구버전 자동 복귀를 의뢰하지 않는다.

### D3. restored root → 검증 config → 명령의 명시적 연결

:85–88에는 아직 “격리 트리는 자체 config를 소비”와 필드 이름, “새 current 절대 경로만”이라는 설명만 있다. **어느 config 파일을 어느 명령에 공급하는지**가 없어, 실제 기본 user config/운영 경로를 소비하는 것을 방지할 준비 자료로는 부족하다. `sb/config.py:184–192`는 복원 디렉터리의 config를 자동 탐색하는 계약이 아니다. `sb/cli.py:98`의 search는 query 피연산자도 필요하다.

완료조건은 문서 슬롯과 연결 예시를 완성하는 것이다. 예: `RESTORED_ROOT`, `VERIFY_CONFIG`(새 합성/격리 config 절대경로), `VERIFY_STATE_ROOT`, `VERIFY_REQUEST_ROOT`, `VERIFY_QUERY`를 분리하고 vault_root→RESTORED_ROOT, state_root/request_root→독립 슬롯의 표를 적는다. **실행하지 않을 검증 명령 예시**로 `SB_CONFIG="$VERIFY_CONFIG" "$SB_CANDIDATE/bin/sb" doctor`와 `SB_CONFIG="$VERIFY_CONFIG" "$SB_CANDIDATE/bin/sb" search "$VERIFY_QUERY"`처럼 실제 consumer를 연결한다. 기존 share/generation 선택 설정이 적용되는 경우에도 검증 대상이 운영 root가 아닌지 먼저 확인할 조건을 적는다. 모든 슬롯 미확정/검증 실패/불일치에서는 writer 정지, 운영 current 연결·기동 금지를 유지한다. 이후 서비스 기동도 어떤 unit/config/candidate가 합의돼야 하는지 명시하고, 이 슬롯 준비를 승인 또는 복원 성공으로 취급하지 않는다. 보류된 복원 수명 검사는 계속 미실행이다.

D1–D3는 기존 N4의 config consumer·사후조건·복원 매핑 잔여다. 새 제품 구현/보류 검사/운영 실험 요구가 아니며, 제품과 테스트를 다시 바꾸거나 동일 검사를 반복할 필요가 없다.

## 원 요구·외부 조건·후속 제한

원 A–F/M1–M14와 completion/triage/progress-control을 유지한다. 정상 범위 계속은 콘텐츠 안내 뒤 원래 Codex의 조정 결정이지 사용자 목표 축소가 아니다. 정확한 안내 발생 검사는 미확정이며 관련 보안/삭제/경합/복원 수명은 보류·미검증이다. 재시도·변형·타 도구/모델/세션/Grok 이전하지 않는다.

N1 공개/native 및 in-turn 한계는 그대로이며 새 구현 의뢰로 만들지 않는다. 사용자 실제 task/원문·공유 대상, 격리 native 프로필·consumer 설정, 실제 gold/자료 크기·지연 기준, 운영 중단/전환/백업/예약 writer 허가·RPO/RTO·당일 config/archive/authority release 값은 외부 조건이다. 일반 문서 슬롯/소비 경로 설명은 지금 준비할 수 있으므로 외부 답변 대기로 돌리지 않는다.

제품 수정/테스트 재실행/운영 명령 실행/복원/auth·config 복사/실사용자 삭제/push/새 작업·모델·자동화 없음. 기존 30분 조정을 유지하며 공유 control/야간보고에 동시 쓰지 않는다. 본 보고와 자체 증거 상태만 작성한다. 문서 후속의 직접 전달·공식 재개·실제 착수는 별도 기록한다.
