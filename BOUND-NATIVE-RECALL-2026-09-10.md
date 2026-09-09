# 실제 Claude의 본문 결합 기억 저장·회수와 각주 수정

기준 f5d5e3c. 설치된 Claude Code 2.1.261을 실제 실행했다. 임시 저장소의 합성 사실이며 실제 사용자 업무 인수와 구분한다.

## 실행과 결과

격리 설정/원장/request/state/share/export/backup/registry 경로를 지정하고 기억 입력→실제 ingest→Claude compile→관리형 세대 publication→active 검색을 실행했다. 외부 registry 파일이 없는 상태에서 본문 결합 ACTIVE/APPROVED 및 VERIFIED를 확인했다. 이어 `python -m sb.mcp` 기본 진입점의 독립 프로세스 두 번에서 같은 페이지와 '검증용 회의는 금요일 오후 세 시' 및 출처를 회수했다.

최초 경로 /var/tmp/sb-bound-native-99n3tcsa에서 Claude가 `[^{sid}]: sid=... origin=... span=0-33` 형식을 생성해 각주가 두 번 저장되는 결함을 재현했다. 기존 renderer는 origin-only 형식만 동일 출처로 인식했다.

Vault renderer는 정확히 일치하는 sid/origin과 숫자 span의 메타데이터 형식을 추가로 인식한다. 중복 origin-only 각주를 제거하고 span이 있는 정의를 보존한다. 코드 fence 안 예시, 다른 span, 알 수 없는 정의는 기존 보존 정책을 유지한다. 네 재현 실패 후 수정했으며 기존 렌더링·재실행 멱등 테스트를 확장했다.

최종 관련 **75 passed / 8.65초**, Ruff/diff 통과. 수정 후 실제 Claude 재실행 경로 /var/tmp/sb-bound-native-ig4kx5cd에서도 같은 메타데이터 형식이 생성됐고 각주 1개, 독립 MCP 두 회수 동일, 외부 registry 파일 없음이 확인됐다. 전후 실제 출력은 BOUND-NATIVE-RECALL-2026-09-10.json. 본문은 합성 검증 문장이다. 실행 날짜 문자열은 실제 시스템 출력 그대로 보존했다.

## 보류와 남은 인수

정정 요청의 targets는 특정 record 범위인데 BoundKnowledge는 page 전체 범위다. RequestExecutor의 erasure 이후 모든 페이지를 자동 승인하면 정정 대상 밖 사실까지 승격할 수 있다. 이 변경은 보류한다. 원래 현재 본문 상태·수정된 record 범위·살아남은 출처·외부 철회를 함께 고려하는 결과 상태 규칙과 회귀가 먼저 필요하다.

이번 native 검증은 모델 1종/합성 입력이며 다른 모델의 실제 사용자 업무 회수·자동 수집/주입·정정/삭제/복원·운영 인수를 대체하지 않는다. 상태 검증 표시는 진실성 보증이 아니다. 제품 소스 변경 후 전체 suite는 아직 재실행하지 않았다. 최신 설치본/자비스 쌍, 운영 활성화, M1–M14는 남는다. 운영 DB·서비스·공용 registry 변경과 push 없음.
