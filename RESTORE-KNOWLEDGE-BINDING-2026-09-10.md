# 검증된 전체 백업의 지식 상태 복원

기준 제품 747bea4 이후 구현. 인계 방향인 세컨드브레인 정본 유지·자비스 및 여러 에이전트 공통 기억의 연속성을 위한 복원 보강이다.

기존 sanitizer는 파생 SQLite를 제거하므로 정상 백업의 승인 상태도 잃었다. 이제 generation.json이 있는 전체 백업은 운영 journal의 원본 세대 digest와 봉인 manifest를 검증하고, 원장의 현재 record와 일치하는 BoundKnowledge만 추출한다. 삭제 정제 이후에도 본문 SHA-256이 정확히 같은 페이지의 상태만 새 원장에 transaction으로 저장한다. 백업 SQLite 자체는 복사하지 않는다.

상태의 page_id·content_digest·knowledge_status·approval_status를 UTF-8로 검사한다. 운영 원장의 검증된 tombstone snapshot과 기존 bounded scanner를 사용하며, 삭제 대상 내용이 포함된 상태는 제외한다. 각 행마다 검사 한도를 초기화하지 않는다. 한글을 JSON escape하여 검사를 우회하지 않도록 실제 문자열 bytes를 검사한다. 승인 상태는 접근 권한이나 사실의 진실성을 보증하지 않는다.

검증된 전체 백업을 실제 sanitizer에 통과시켜 삭제 대상은 검색되지 않고, 그대로 남은 승인 기억은 active 검색에서 VERIFIED이며, 백업에 나중에 추가한 문서는 승격되지 않는 것을 확인했다. 후보 세대만 생성하며 운영 active pointer는 바뀌지 않는다. 콘텐츠만 있는 기존 백업은 상태 없이 복원한다. 전체 세대 백업이 원본 근거를 검증하지 못하면 실패한다.

검증: `TMPDIR=/var/tmp uv run pytest -q tests/test_restore.py tests/test_restore_source.py tests/test_restore_knowledge.py tests/test_restore_inventory_spans.py tests/integration/test_memory_restore_reingress.py --tb=short` — **43 passed / 33.72초**. Ruff 전체 통과, restore·restore_knowledge·restore_inventory 타입 **0오류/0경고**, diff 검사 통과. 첫 실행은 새 코드의 상태 필드명 오류로 5실패/38통과였으며 실제 필드명으로 수정한 뒤 위 범위를 전부 재실행했다. 최신 변경에 대한 전체 suite는 아직 실행하지 않았다.

남은 우선순위:

1. **접근 분류 복원:** 검증된 source/page 접근 요구사항도 정제 본문과 결합하고, 다른 사용자·프로젝트·정책이 조회할 수 없는지 실제 경로에서 검증한다. 현재 지식 상태 복원만으로 scoped 공통 기억 복원이 완료되지는 않는다.
2. **재해 복구:** 운영 journal까지 소실된 경우 독립 신뢰 근거를 확보해야 한다. 백업이 스스로 주장하는 digest만으로 승인하지 않는다.
3. **실제 운영 인수:** 최신 provider/JARVIS 조합, 실제 사용자 작업의 저장→새 에이전트 회수→정정/삭제와 native 세션·캐시 수명까지 검증한다.
4. **검색·클라이언트 고도화:** 실제 한국어 질문 평가, 에이전트별 자동 수집·문맥 공급, GUI 및 운영 복구를 통합 계획의 완료 조건에 따라 이어간다.

운영 DB·서비스·공용 registry 변경 및 push 없음. 전체 M1–M14 목표는 아직 미완료다.
