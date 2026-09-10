# OpenCode 여러 저장 위치의 출처 분리

두 root에 같은 snapshot 상대 경로·항목 ID·본문이 있으면 기존 OpenCode 어댑터는 완전히 같은 SourceRef 두 개를 반환하고 커서 키도 공유했다. 원장 중복 제거 과정에서 서로 다른 원문이 합쳐질 수 있었다. 새 테스트에서 최초 및 구형 커서 재개 모두 이를 재현했다.

다른 세션 어댑터와 pipeline에 이미 구현된 ambiguous-session-roots/SOURCE_ROOTS_AMBIGUOUS 규칙을 OpenCode에도 적용했다. 하나의 어댑터/source ID에 여러 root를 암묵적으로 묶는 방식은 보류한다. 본문을 읽거나 커서를 소비하지 않으며 기존 cursor 문자열을 보존한다. pipeline의 기존 처리에 따라 오류로 보고되어 반복 실행에서도 숨겨지지 않는다.

지원하는 여러 root 연결은 각 root에 고유한 sources.id를 선언하는 기존 경로다. pipeline._select_adapters는 설정 행을 격리해 어댑터를 생성하므로 이 경로는 계속 동작한다. registry나 SourceRef 형식을 바꾸지 않았다. 과거 source ID를 임의로 재명명하는 마이그레이션도 수행하지 않았다.

```toml
[[sources]]
id = "opencode-personal"
adapter = "opencode-sessions"
root = "/path/to/personal-export"
llm_policy = "local-only"

[[sources]]
id = "opencode-work"
adapter = "opencode-sessions"
root = "/path/to/work-export"
llm_policy = "local-only"
```

위는 신규 설정 예시이며 기존 출처·정정/삭제 이력이 있는 운영 설정을 그대로 교체하라는 뜻이 아니다. source ID는 출처 식별자이고, 그 자체가 사용자/프로젝트 접근 권한을 설정하는 것은 아니다.

검증: 관련 테스트 74 passed / 0.77초, 전체 sb/tests Ruff 및 변경 모듈 basedpyright 통과. 실제 격리 CLI init 후 ingest 3회 모두 exit 0: 동일 항목/본문을 가진 agent-a/b 두 출처가 원장에 별도 존재하고 CAS 본문만 공유함을 확인했다. A만 변경하면 A 이력 2개/B 이력 1개가 남고 B 커서는 동일하다. 재실행 원장·커서 불변. 결과 원본 OPENCODE-SOURCE-ISOLATION-2026-09-10.json, 환경 /var/tmp/sb-opencode-multi-source-ewpu5j96.

합성 export 기반 실제 CLI 검사이며 native OpenCode 프로세스 연결·자동 주입·운영 배포 완료를 의미하지 않는다. 참조 SQLite 읽기 중 교체와 전체 운영 인수는 남는다. 전체 회귀/설치 paired 인수는 이번 수정 뒤 재실행하지 않았다.

추가 통합 검증: tests/integration/test_session_source_isolation.py **9 passed / 28.60초**. OpenCode의 모호한 설정에 대해 별도 CLI 프로세스 2회 모두 비정상 종료·SOURCE_ROOTS_AMBIGUOUS를 확인했고 원장 source_items/cursors가 비어 있었다. 다른 4종 세션의 기존 명시적 출처 분리 및 모호한 설정 거부도 함께 통과했다.
