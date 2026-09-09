# 배치·충돌·웹 누적 수정의 전체 회귀 및 설치 연동

제품 소스 `40c7baa4582f0a0722b4a20496e3ec64284c337b`에서 기본 전체 검사 실행: **1541 passed, 2 failed, 2 skipped, 378.47초**. 선택적 embeddings 테스트는 저장소 기본 규칙대로 제외했다.

두 실패는 runtime_reliability와 scoped_search의 모델 대역이 충돌 JSON 계약을 충족하지 않은 데서 발생했다. 전자는 verdict/compatible이라는 지원하지 않는 필드·값, 후자는 JSON 대신 일반 텍스트/배열을 반환했다. 새 오류 집계가 실제 실패를 드러냈다. 제품의 오류 처리를 완화하지 않고 두 테스트 모델의 json_mode 응답을 relation/unrelated·confidence·rationale·cites로 수정했다.

실패 파일 두 개와 충돌/재시도 회귀를 다시 실행해 **22 passed, 6.28초**, Ruff/diff 통과. 전체 스위트를 수정 후 다시 실행한 것은 아니므로 처음부터 전체가 통과했다고 보고하지 않는다. [원본 로그 및 타입 검사](POST-CONFLICT-REGRESSION-2026-09-09.txt).

변경 모듈 basedpyright는 **0 errors, 7 warnings**. 비공개 마스킹 함수 사용, SQL row Any 및 기존 경고가 포함된다. 경고를 제거한 것으로 표현하지 않는다.

## 최신 설치 후보

같은 소스 커밋을 독립 캐시 사본으로 offline 준비했다. 후보:

`/var/tmp/sb-conflict-release-3ld7u2vj/app/releases/208abc402017a6a20fe1e203de2c137a2a34345c`

기존 자비스 `195b1a7` 격리 빌드와 실제 TLS/gateway/CLI/MCP 연동 네 경로를 확인했다. 정상 proved→settled→completed 및 새 로그인 회수, 접수 중 철회 차단, 실행 전 철회·만료 실패가 통과했다. 모델/native 사용자 업무는 fixture와 구분한다.

검사 전후 provider 18,456항목 digest `7402375b588df017345d48ccc1171d14812ae5033dacb2cb9ae4ddfe54e490ac`, 자비스 19,588항목 digest `8b3ebc1901256636f33c6218adee47d6e294355afd64b569af343ea7676b8d10`가 동일했다. [연동 증거](POST-CONFLICT-REGRESSION-2026-09-09.json).

이번 커밋은 테스트와 보고서만 수정한다. 새 후보의 정본 manifest·재현 쌍·운영 활성화는 미완료이며 운영 DB·서비스·현재 포인터를 바꾸지 않았다. 실제 업무 공유·모델 품질·전체 삭제 수명·M1–M14 운영 인수는 계속 남는다.
