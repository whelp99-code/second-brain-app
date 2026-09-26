# Second Brain 2 — 구현 및 인수 범위

이 문서는 P00–P14의 구현 위치와 실제 검증 방법을 연결한다. 배포 전 개발 후보 문서이며, 자동 검사 통과를 Mac/iPhone 실기기·운영 인수로 바꾸지 않는다. 이번 변경의 테스트 숫자와 커밋은 별도 실행 증거로 확인한다.

## 작업 기준 및 변경 보존

실제 Ubuntu 앱 경로는 `/home/jm/orca/projects/second-brain-app`이다. Mac의 이전 `/Volumes/DevSpace/second-brain-app` 경로는 이번 연결에서 존재하지 않았고, 등록된 `/Volumes/DevSpace/Playground` 또한 존재하지 않았다. 네이티브 빌드 성공을 주장하지 않는다.

작업 브랜치: `feat/sb2-life-intelligence-20260926-6c57b834`. 이번 마무리 작업 이전 HEAD는 `ab6a1db`다. 사용자의 기존 `.gitignore`와 `docs/second-brain-guide.html` 변경은 그대로 보존하고 기능 커밋에서 제외한다. 마무리 시작 시점의 변경 파일, 바이너리 diff, 원본 파일 묶음은 `.chatgpt2codex/sb2-completion-20260926/`에 보존했다.

## P00–P14 추적표

| 작업 | 구현 위치 | 재현 가능한 검증 | 별도 남는 인수 |
|---|---|---|---|
| P00 기준선·규칙·복구 | 루트 AGENTS, baseline.json, 본 문서 | 작업 전후 hash와 Git 상태 비교 | Mac 작업공간·Xcode 연결 |
| P01 사건·시간 계약 | life_contracts, life_values, life_config | test_life_contracts, test_life_policy_views | 실제 출처 시간 품질 |
| P02 원장·개정·삭제 | store/life, store/life_journal, life_restore | test_life_store, test_life_restore_preservation | 운영 자료의 선택 표본 인수 |
| P03 입력 어댑터 | connectors/records_life, life_exports/imports/ingest | test_life_export_ingest | 실제 계정의 허용 export/API 계약 |
| P04 iPhone 접수 | life_phone, Core/LifeMemoryBridge, SyncService | test_life_auth_cli_boundary, Phone History 계약 검사 | 실제 iPhone 공유→서버 접수 |
| P05 타임라인·관계 | life_timeline_query, life_views, life_relations | test_life_workflow_objects/http, auth_cli_boundary | 10만 사건 성능 목표 별도 측정 |
| P06 Obsidian | clients/obsidian/, life_projection | npm test/check/build, 분할·중단·충돌·철회 검사 | Mac/iPhone 설치·업데이트·오프라인 사용 |
| P07 브리핑·전달 | life_delivery, life_cli, life_workflow | test_life_transport_runtime, workflow_http | 실제 알림 채널·사용자 열람 |
| P08 질문 | life_questions, workflow | budget/quiet-hours/응답·차단·동시 실행 검사 | 실제 질문 관련성·방해 정도 |
| P09 과거·현재 회상 | life_recall, life_visibility, 기존 search/MCP 연결 | synthetic 300문항, 정정·시점·범위 검사 | 사람의 정답 검토·동의어/의미 검색 품질 |
| P10 모델 정책 | life_model_policy, life_cli, llm | 예산·local-only·잘못된 인용·프로세스 검사 | 실제 모델 품질·실사용 비용 |
| P11 운영·복구 | life_lock/restore, pipeline, ops, verify_sb2_scope | 강제 종료·복원·동시성·전체 회귀·패키지 | 운영 활성화·실제 7일 관찰 |
| P12 위치 | life_sensors, Overland HTTP ingress | test_life_sensor_ingress | 실제 권한·GPS 누락·배터리 |
| P13 건강 | App/LifeHealthBridge, health ingress | Phone predevice, 삭제·단위·결측·수면 중복 검사 | Xcode 빌드·실기기 권한/삭제 |
| P14 예측 | life_predictions, journal | cutoff·사전 고정·실제값 개정·미채점 검사 | 적격 실제 표본과 기준선 비교 |

## 구조 결정

기존 CAS 원본, ledger, 커밋된 Vault, 검색을 유지한다. 생활기록 저장은 같은 ledger 체계의 테이블과 개정 원장을 확장하며 별도 DB 서버를 만들지 않는다. 커넥터는 읽기 전용 원본을 제공하고, pipeline이 정규화와 정책을 적용하며, Vault 작성자가 관리형 페이지를 게시한다. 사건 ID·기존 MemoryRecord 계약을 전면 재생성하지 않는다.

상주 이벤트 버스·워커는 추가하지 않는다. `sb life tick`, `sb life maintain`, `sb life ingest`는 한 번 실행하고 종료한다. 외부 스케줄러 설치나 센서·알림 활성화는 이번 코드 작업의 자동 부수효과가 아니다. 과거 설계의 승인/권한 서비스와 혼동하지 않고 기존 실행 경계를 유지한다.

상태는 분리한다. 접수증 존재, 사건 개정, 검색/뷰 게시, 전송 수락, 실제 열람은 서로 다른 증거다. 기기에서 대기 기록을 지울 때는 명시적인 내용 결합 접수증이 필요하다. `generated`, `transport_accepted`, `opened`를 같은 상태로 표시하지 않는다.

## 이번 마무리에서 수정한 결함

웹 JSON 응답의 생활기록 인증 재검사는 실제 생활기록 요청에만 적용한다. 불완전하게 구성된 연결 오류 처리기에는 요청 path를 강제로 요구하지 않는다.

복원과 쓰기가 공유하는 바깥 잠금은 디렉터리 교체 밖에 유지하고 해제 후 파일을 삭제하지 않는다. generator context manager가 frozen 도메인 예외의 traceback을 수정해 원래 오류를 가리던 문제는 class context manager로 해결한다. 잘못된 상대 경로 입력은 원래 검증 오류를 반환한다.

실제 iPhone의 quick_note/text_shared/webpage_saved/file_shared 입력을 서버의 note_saved/link_saved/document_saved·audio_saved·photo_saved로 정규화한다. task_started와 activity_started는 완료와 별도 사건으로 보존한다. 클라이언트의 더 높은 민감도는 낮은 출처 등급으로 내리지 않고 입력을 거절한다. 파일·통화 수집 출처는 해당 민감도 및 local-only 정책으로 명시 설정해야 한다.

iPhone의 `device_id`는 PhoneEvent v1의 사건 내부 필드가 아니라 batch envelope 필드다. 사건 생성 시 존재하지 않는 필드 매핑을 요구하지 않으며, 서로 다른 기기의 기록을 한 batch로 보내지 않는다. Share Extension에는 필요한 생성 계약 파일을 포함한다. 호스트 앱을 import하는 테스트 타깃에서 Core를 중복 컴파일하지 않는다.

새 서버로 주소를 바꿀 때 기존 Keychain 토큰을 자동 재사용하지 않는다. 설정 버전이 바뀌면 전송 중 응답을 적용하지 않고 원본 대기열을 보존한다. 건강 조회 위치도 동일한 설정 버전과 명시적 영속 접수 이후에만 갱신한다.

모델은 실제 입력에 포함된 최대 40개 사건만 인용할 수 있다. 전체 권한 집합 안에 있더라도 모델에 보내지 않은 41번째 사건의 ID를 근거로 돌려주면 거절한다. 외부 처리 정책과 예산 예약은 호출 전에 적용하고, 결과 불명 시 예약 비용을 무료 호출로 초기화하지 않는다. CLI가 실제 토큰 비용을 보고하지 않는 경우에는 측정값 없음과 예약 상한을 구분한다.

## 안전한 후보 실행

`docs/SB2_SAFE_DEFAULTS.toml`은 모든 기능 OFF, 모든 입력 OFF, 외부 모델·전달 채널 미설정의 예제다. 운영 설정 파일을 덮어쓰지 말고 별도 디렉터리로 복사해 사용한다. 위치·건강 데이터를 시험 메모와 동일한 공개 출처로 연결하지 않는다.

합성 메모 후보만 시험하려면 예제 복사본에서 `life_events`, `life_timeline`, `obsidian_view`, `life_briefing`, `contextual_recall`과 `life.sources.demo-notes.enabled`만 true로 설정한다. 나머지 기능과 출처는 OFF를 유지한다. 해당 설정 파일을 `SB_CONFIG`로 지정한 후 다음 실제 CLI를 사용한다.

```sh
sb init
sb life health --source demo-notes
sb life import --source demo-notes --format life-json --raw-file ./synthetic-events.json
sb life timeline --source demo-notes --day 2026-09-26
sb life recall --source demo-notes --query '합성 메모'
sb life manifest --source demo-notes --day 2026-09-26
sb life maintain --source demo-notes
```

`synthetic-events.json`의 실제 계약 예제는 `tests/test_life_export_ingest.py`와 `tests/test_life_contracts.py`를 따른다. 비밀값이나 개인 자료를 `--data`로 셸 이력에 넣지 않는다. 접수와 메모 반영은 반환된 실제 state/receipt로 확인한다.

기본 import 형식은 `life-json`, `phone-event`, `google-calendar`, `graph-calendar`, `mail-eml`, `mail-json`, `document`, `conversation`, `audio`, `photo`다. 위치/건강 ingress는 별도 opt-in 정책을 적용한다. DOCX/XLSX/PPTX 원본은 ZIP 경로·구성 항목·용량 상한을 검사해 보존하지만 내용을 자동 실행·추출하지 않는다. 녹음 파일 보존이 자동 전사 완료를 의미하지 않는다. 캘린더 export에 반복 규칙만 있고 개별 일정이 없을 때 전체 occurrence를 수집한 것으로 과장하지 않는다.

## 인증과 클라이언트

기존 관리자 `SB_WEB_TOKEN`과 기기 전용 토큰을 분리한다. `life_devices.<device-id>`에는 `token_env`, `source_ids`, `can_write`, `expires_at`, `revoked`만 설정한다. 토큰 값은 Git·Obsidian 설정에 넣지 않는다. 기기 토큰은 관리자 run/withdrawal 권한이 아니며 지정 출처와 만료를 검사한다. 운영 설정 재로딩 실패나 응답 직전 정책 변경은 실패 상태로 차단한다.

Obsidian은 전용 View Vault의 `Auto/`만 관리한다. 각 파일과 전체 generation의 hash를 확인한 다음 적용하고, 모든 페이지를 받기 전에 완전한 snapshot이라고 취급하지 않는다. 사용자가 고친 Auto 파일은 충돌로 보존하며 `MyNotes/`는 자동 수정·삭제하지 않는다. 명시적 개인 메모 저장은 새 원본 수집이다. 토큰은 세션 메모리에만 보관한다. 장기 오프라인 사본·사용자 수정본·백업의 즉시 물리 삭제는 보장하지 않는다.

HealthKit은 앱에서 선택한 수면·걸음 수·심박·HRV 종류에 한해 읽기 요청한다. 기본 선택은 없고 foreground 동기화도 기본 OFF다. `toShare: []`를 유지하며 Share Extension에는 HealthKit·네트워크 코드·권한을 넣지 않는다. 읽기 권한 요청이 끝났다는 결과를 실제 읽기 허용이라고 해석하지 않는다. 앱 privacy manifest에 건강/피트니스 수집을 명시하고 앱 기능 목적·비추적 원칙을 유지한다.

## 자동 검증과 빌드

```sh
uv run --offline ruff check sb tests
uv run --offline pytest -q --tb=short
make -C phone-history verify PYTHON="$PWD/.venv/bin/python"
(cd clients/obsidian && npm test && npm run check && npm run build)
uv build --offline
```

전체 묶음 검증은 다음 명령으로 시작하고 **finished 및 automated_gate_pass를 실제 확인**한다. 재실행은 새로운 출력 경로를 사용해 과거 실패 증거를 덮지 않는다.

```sh
.venv/bin/python scripts/verify_sb2_scope.py start --output .chatgpt2codex/sb2-check-01
.venv/bin/python scripts/verify_sb2_scope.py status --output .chatgpt2codex/sb2-check-01
```

source-manifest는 서버·테스트·클라이언트·Swift·privacy manifest·생성기·검증 스크립트를 포함한다. 테스트 중 소스가 달라지면 전체 PASS가 아니다. 선택적으로 제외된 실제 DB/모델/임베딩 검사는 skip 사유와 함께 남긴다. 300문항은 합성 계약 평가이고, 모두 통과해도 실제 사람 질문의 의미 정확도 100%로 표현하지 않는다.

Phone History의 별도 wheel은 선언된 hatchling 빌드 의존성이 필요하다. 현재 환경에서 해당 의존성의 네트워크 다운로드 요청은 승인 게이트에 걸렸다. 소스 묶음·서버 검사 통과와 별도 wheel 설치 성공은 구분한다. 필요한 공식 빌드 의존성이 승인 후 제공되면 `uv build phone-history`로 빌드한다. 도구 승인 게이트를 우회하는 설치는 하지 않는다.

## 출시 판단

자동 검사 결과가 PASS여도 현재 후보의 **실기기/운영 출시 판단은 NO_GO**다. Mac/iPhone 네이티브 빌드·서명·실제 공유, Obsidian 설치/재접속, 실제 센서 권한·배터리, 실제 모델 품질·비용, 운영 채널과 7일 관찰 결과가 있어야 각 인수 항목을 닫을 수 있다. 운영 서비스·포트·터널·자격증명·원본 계정은 이번 코드 작업으로 변경하지 않는다.

기존 사용자 변경이 남은 작업 트리를 clean으로 만들기 위해 reset/stash하지 않는다. 검증된 기능 파일만 커밋하고 나머지 파일의 hash를 보존한다. push·master 병합·운영 활성화는 실행하지 않는다.
