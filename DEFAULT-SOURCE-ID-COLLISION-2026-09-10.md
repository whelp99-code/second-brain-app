# 기본 source ID와 잘못된 adapter 이름의 충돌

설정 `{id: inbox, adapter: missing-adapter}`로 실제 discover_adapters와 _select_adapters를 호출했다. InboxDocumentsAdapter/source_id=inbox가 선택됐다. 원본 scan은 실행하지 않았다. [재현 증거](DEFAULT-SOURCE-ID-COLLISION-2026-09-10.json).

현재 선택기는 설정 ID와 adapter.source_id가 같으면 연결된 것으로 판단한다. inbox factory는 지원하지 않는 adapter 이름을 무시하고 기본 inbox adapter를 반환하므로, ID가 기본값과 같으면 이전 SOURCE_NOT_FOUND 검사를 통과한다. 임의 ID/없는 adapter의 거부는 구현됐지만 모든 adapter 이름 검증이 완료된 것은 아니다.

이 결손은 설정된 root 대신 기본 root를 사용할 가능성이 있어 후속 수정 우선순위가 높다. alias를 사용하는 정상 설정을 깨뜨리지 않도록 각 모듈이 수락한 adapter 이름을 판별하는 공통 인터페이스와 기존 factory 호환을 함께 검증해야 한다. 기본 ID 이름만 금지하거나 alias를 제거해 문제를 피하지 않는다.

이번 턴에서는 전체 회귀 대상 소스를 유지했고 이 결손의 수정은 아직 하지 않았다. 재현은 임시 경로의 adapter 선택까지만 수행해 원문·운영 저장소 수집은 하지 않았다. 전체 M1–M14와 운영 인수는 남는다.
