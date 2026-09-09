# 배치 설명과 단계 오류의 응답 필드 분리

전체 배치의 selected_run_id/stages JSON이 최근 실행 이력의 error로 반환됐다. 정상 배치에도 오류 문자열이 있는 것처럼 보였고, 부분 실패 배치의 실제 오류 설명과도 구분되지 않았다. 기존 부분 실패 회귀에 이 조건을 추가해 재현했다.

배치 row의 설명은 detail로, 개별 단계의 오류는 기존 error로 반환한다. batch 상태와 오류 합계는 그대로 유지한다. 배치의 예외·중단 설명도 detail에 남긴다. 두 문자열 모두 기존 자격증명 마스킹·길이 제한을 적용한다. 전체 JSON 계보를 새 구조화 API로 제공한 것은 아니다.

관련 run_all/ops/web/ordinary·managed batch crash **46 passed / 12.24초**, Ruff/diff 통과. 기존 관리형 임시 저장소의 실제 HTTP 상태 응답에서도 batch error는 비어 있고 detail이 있으며, 과거 ingest 오류 문자열은 남는 것을 확인했다. [실행 응답](BATCH-DETAIL-FIELD-2026-09-10.json). 서버 종료, 운영 데이터 변경 없음.

최신 설치 반영·관리형 승인/본문 결합·실제 업무 공유·운영 및 M1–M14는 남는다.
