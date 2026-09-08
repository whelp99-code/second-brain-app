# 자비스 기억 화면의 개인정보·검색 수명 수정

제품 `53136d4` (JARVIS), 브라우저 인수 도구 `bc3313b` (SB). 이전 JSON 사본 삭제 보강 다음 단위다.
기존 실제 앱 경로를 대조했고, 대시보드의 조회와 표시에서 다음 문제를 재현·수정했다.

| 발견 | 적용한 수정 | 확인한 결과 |
|---|---|---|
| provider를 기다리는 동안 정책·session이 바뀌어도 검색/충돌 응답을 반환 | await 전후 전체 로컬 상태 비교, 최종 projection/suppression/token 발급을 한 read transaction으로 결합 | 변경 시 HTTP409, 기억 본문 없음 |
| 충돌 목록이 suppression을 적용하지 않음 | 양쪽 중 하나라도 억제되면 전체 충돌 제외 | 실제 owner 승인 후 목록0/no_data |
| privacy clear 뒤 선택 상세·수정 초안이 남음 | 현재 검색 token에서만 상세를 선택, key로 컴포넌트 수명 분리 | 이전 내용·draft·삭제 확인 제거 |
| 검색 자체 만료 시각을 무시 | 결과 freshness timer, status 만료 때 private clear, 지연 응답 epoch 검사 | 만료 뒤 늦은 응답으로 재표시되지 않음 |
| 새 정책 epoch 결과를 예전 화면 상태에 수용 | status privacy_epoch와 검색 epoch 대조 | 불일치 결과 폐기 |
| 같은 object/token 재사용으로 예전 action 완료가 새 화면에 영향 | 로컬 view_revision을 key 및 callback에 결합, unmount 완료 차단 | 즉시 응답 batching에서도 이전 완료 무시 |
| 개인정보 clear 후 입력 검색어도 잔류 | clear_revision에서 검색 form 재생성 | 실제 Chromium 검색어 공백 확인 |
| 만료 경고가 정상 검색 후에도 계속 표시 | 검색 시작에서 이전 message 제거 | 정상 결과·상태 표시 회복 |

초기 backend4실패 중 detail은 테스트의 tombstone root가 달라 provider 호출 전 종료된 것이므로
실제 누출 재현으로 세지 않는다. 최종 테스트는 root를 바로잡아 provider 이후 session 변경을
거부하는 경로를 확인한다. frontend 초기3실패는 내용 잔류·만료 누락·epoch 불일치를 직접 재현했다.

## 검증 범위와 결과

- Backend 관련5파일15 passed, 최종 충돌 no_data 보강 후2파일6 passed.
- Dashboard 전체34파일211 passed (30.40초), 마지막 상태메시지 보강 후 집중6 passed.
- 위 결과는 중복을 포함하므로 합산하지 않는다. backend/dashboard TypeScript, 변경 ESLint,
  격리 backend emit 및 Vite build, diff 검사 통과. JARVIS 전체 backend verify나 SB 전체 회귀는 아니다.
- 독립 모델 검토의 동일 객체 재사용·지연 응답·오류 메시지 지적을 반영했다. 최종 추가 차단 지적 없음.

[기계 증거](DASHBOARD-MEMORY-LIFETIME-2026-09-08.json). 격리 build는
`/var/tmp/jarvis-view-build-8f9udiqk`, 최종 실행 결과는
`/var/tmp/jarvis-view-browser-yDITvd/result.json`. 해당 프로세스 exit0, 검증 서버·브라우저는 종료했다.

## 실제 화면 QA

검증 흐름: `/memory` → 검색 → 상세 선택 → 수정 draft/삭제 확인 → privacy SSE → 목록·상세·draft·검색어 제거.
URL은 `http://127.0.0.1:43863/memory`, Chromium1440×1000 및1024×1000이다. Browser plugin not available로
설치된 Playwright를 사용했다. provider는 결정적 합성 adapter이며 운영 vault·모델·실제 사용자 데이터는 사용하지 않았다.

| 검사 | 결과 |
|---|---|
| 페이지 식별 | 두 화면 모두 /memory, 제목 JARVIS 현황판 |
| 빈 화면 | Memory 화면·검색·상세·충돌·후보 영역 렌더링 |
| framework 오류 overlay | 0 |
| console warning/error·pageerror | 0 |
| screenshot | 각 viewport 선택 전후4개 저장, 최종1024 제거 화면 시각 확인 |
| 실제 상호작용 | 개인정보 SSE 이후 검색어·결과·상세·draft·확인 제거 |
| 가로 overflow | 두 viewport 모두 없음 |
| 실제 HTTP 경합 | provider 응답 중 정책 변경 시409 / MEMORY_SURFACE_READ_CHANGED / 본문 없음 |

상단 전역 연결 배지는 **끊김**으로 관측됐다. 이번 Memory SSE 상호작용은 동작했으나 이 결과를
전체 관제 연결/운영 준비의 증거로 확대하지 않는다. Memory의 ready도 현재 adapter 구성 상태다.
Safari·모바일·다른 실제 client·운영 provider까지 검증한 것은 아니다.

재현: 격리 build의 backend/test JS·dashboard assets·migrations·contracts·config/personal-os-policy.json·
node_modules를 준비하고 `TMPDIR=/var/tmp node scripts/jarvis-memory-view-acceptance.mjs /absolute/build`.
일반 dist나 운영 DB를 변경하지 않는다. 실행은 합성 DB/키/화면을 만들며 screenshot/fixture 자료는 남는다.

## 새로 발견한 다음 수정과 기존 미완료 조건

SB cwd에서 첫 재실행은 `composeRemoteApproval`의 상대 경로 `config/personal-os-policy.json` 부재로
HTTP 요청 처리 중 프로세스가 종료됐다(exit1). 인수 도구는 격리 build config를 준비하고 cwd를
그곳으로 지정해 재실행했다. **제품의 상대경로 의존·요청마다 설정 조립·설정 실패 시 종료는
아직 고치지 않았다.** 다음 단위에서 시작 시 설정 검증과 고정된 경로/서비스 수명으로 수정한다.
증거 `/var/tmp/jarvis-view-browser-final3.log`, 현재 `src/remote-approval-compose.ts` 및 dashboard server.

JARVIS task provider는 승인된 execution-plan digest와 source snapshot으로 prompt를 만든다.
검증 없이 memory를 뒤에 붙이는 자동 연결은 보류한다. native 원문 관리·수신 fence·compaction·
프로젝트/사용자 ACL·검증된 자동capture·검색 근거 충분성/속도·실제 질문·운영/DR은 기존 전체 목표로
유지한다. read transaction 종료와 HTTP 전송 사이의 전역 원자성도 이번 변경의 보장이 아니다.
운영 배포·재시작·push는 수행하지 않았다.

최종 선택 후 개인정보 제거 화면:

![1024 화면의 개인정보 제거 후 상태](/var/tmp/jarvis-view-browser-yDITvd/cleared-1024.png)
