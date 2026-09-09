# OMO 실제 모델 기억 호출 — 인증 차단으로 보류

기존 엔진/CLI 초기화 검증 다음 단계로, OMO가 기억 도구를 실제 호출하는 선택적 acceptance를 추가했다. `SB_PHONE_NATIVE_ACCEPTANCE=omo-cursor`와 `SB_OMO_CLI=ABS_OMO_JS`로 실행한다. Composer 2.5와 cursor-cli-oauth를 지정하고 기존에 활성화·설정된 provider 구성 및 해당 OAuth 항목만 임시 agent 디렉터리에 복사한다. 새 승인 상태를 만들지 않으며 만료 임박/미설정이면 중단한다. 기존 사용자 인증 파일에 직접 쓰는 코드는 없다.

허용 도구는 mcp_jarvis_memory_jarvis_memory_context 하나로 지정하고, 추가 _ast_grep 서버를 비활성화한다. 세션 저장과 사용자 프로젝트 파일 탐색을 끈다. 모델이 반환한 최종 문구만으로 성공 처리하지 않고 실제 tool_execution_end의 결과가 기대 기록과 일치하며 정확히 1회인지 검사한다. 기록은 격리된 provider/gateway fixture 내용이다.

## 실제 시도 결과

1. 처음에는 저장된 인증 항목 이름 cursor를 provider 이름으로 오인해 Unknown provider 오류로 모델 호출 전에 종료됐다. 지원 코드에서 cursor-cli-oauth를 확인해 수정했다.
2. 올바른 provider로 실행하자 assistant error 이벤트가 반환됐다. 검사 도구에 credential 값을 제거한 오류 사유 출력을 추가해 한 번 재실행했다.
3. 확인된 사유: **All Cursor CLI OAuth accounts are blocked until re-login.** 만료 시각이 남아 있는 것만으로 인증이 가능하다고 판정할 수 없다. 실제 기억 도구 호출 성공은 검증되지 않았다. 이후 이 인증 상태로 추가 재시도하지 않았다.

이 lane은 재로그인 전 보류다. 로그인 자체나 계정 차단 해제·갱신을 자동으로 수행하지 않았다. 이 실패를 OMO MCP 미지원으로 해석하지 않는다. 엔진과 CLI 등록은 이전 검사에서 통과했고, 모델 provider 인증이 별도 막혔다.

## 회귀와 범위

기본 실행에서는 새 native 경로가 실행되지 않는다. 기본 실제 HTTPS/MCP/CLI 쓰기→새 로그인 읽기·철회/만료 4경로를 재실행해 exit 0을 확인했다. 두 JS 파일 문법 검사 통과. 신규 native helper는 성공 인수가 아닌 보류된 검증 도구다. CLI 공급자 내부 세션/로그 보존의 완전한 삭제도 이번 결과로 입증하지 않는다. 운영 서비스 활성화·실제 업무 기억·전체 M1–M14는 계속 미완료다.
