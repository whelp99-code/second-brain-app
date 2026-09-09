# 배치·설정 수정 후 전체 회귀 통과

소스 bc73959에서 저장소 지정 명령 `uv run pytest -q --ignore=tests/test_embeddings.py`를 다시 실행했다. **1,567 passed, 2 skipped / 305.35초**, 종료0. 이전 예산 fixture3개와 pinned 웹 상태1개의 실패가 해소됐다. [전체 로그](BATCH-FULL-PASS-2026-09-10.txt).

Ruff 및 diff 검사 통과. 최근 수정한 ops/pipeline/web/store 모듈 basedpyright는 **0 errors, 14 warnings**다. [타입 로그](BATCH-STATIC-TYPES-2026-09-10.txt). 경고는 해결됐다고 표현하지 않는다. 선택적 embeddings 테스트는 지정 명령대로 제외했으며, 테스트 실행 중 제품 소스는 변경하지 않았다.

기존 실제 관리형 배치/HTTP 인수는 앞선 실행 증거를 유지한다. 이번 전체 테스트 통과가 운영 전환, 실제 업무·다른 모델 에이전트 공유, 일반 승인 표시와 본문 검증 연결, 강제 종료/복구 및 M1–M14 전체 완료의 증거는 아니다.

추가 대조에서 기본 ID inbox와 존재하지 않는 adapter 이름의 조합이 기본 InboxDocumentsAdapter를 선택하는 결손을 실제 선택 단계에서 확인했다. [재현·후속 수정 범위](DEFAULT-SOURCE-ID-COLLISION-2026-09-10.md). 원본 scan은 실행하지 않았다. 이 결손은 전체 테스트가 아직 포착하지 못하는 미수정 사항이다.
