# 세대 전환 중 기억 저장 보존 — 2026-09-09

직전 파일 읽기 안전성 수정 후, 동시에 추가되는 대기 기억이 세대 전환에서 빠질 수 있는지 대조했다. 일반 GenerationMutationService.remember와 mutate_root의 세대 관리 경로는 mutate의 generation-writer.lock을 공유한다. 웹 /api/uploads와 /api/remember도 이 경로를 사용한다. 따라서 이 경로에 두 번째 잠금이나 별도 복사 큐를 추가하지 않았다.

기존 tests/integration/test_generation_concurrency.py의 실제 프로세스 테스트를 보강했다. 먼저 대기 기억을 저장한 뒤 컴파일 프로세스를 staging 단계에서 파이프로 멈추고, 별도 기억 저장 프로세스를 시작한다. 독자가 기존 세대를 고정한 동안 generation lock과 writer lock의 배타 획득이 실패함을 확인한다. 독자 해제 후 컴파일→기억 저장의 부모 세대 관계를 확인하며, 전환 전 기억과 동시 요청의 기억 본문이 보존되는지 검사한다. 추가 remember로 다음 세대를 만든 뒤 두 본문을 다시 비교한다. sleep에 의존하지 않는다.

실행: uv run pytest -q tests/integration/test_generation_concurrency.py — 5 passed / 10.52초. 같은 모듈의 실제 MCP 병행 읽기·writer 강제 종료·삭제 경계 검사도 통과했다. Ruff 통과.

판정: 세대 관리 쓰기 경로의 대기 기억 보존은 이 시나리오에서 확인됐다. 외부 프로그램이 active 경로에 직접 쓰는 방식, sb_remember의 명시적 레거시 root 분기, share_root가 없는 mutate_root 직접 쓰기 분기는 이 보장의 대상이 아니다. 이 경로들을 운영의 세대 관리 쓰기와 혼용하는 것은 별도 검증 전 보류한다. 실제 웹/CLI 서버를 통한 모든 동시성 조합을 이번 검사로 주장하지 않는다. 운영 설정·서비스·DB 변경 없음. 전체 M1–M14는 계속 미완료다.
