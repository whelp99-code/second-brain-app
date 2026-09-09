# 일반 검색의 승인 표시와 본문 검증 경계

관리형 staging에서는 외부 KnowledgeRegistry 쓰기를 생략한다. 반면 일반 SearchIndex의 봉인 lexical 경로는 외부 registry snapshot에서 page_id로 상태를 찾는다. source_hash 필드가 있지만 검색은 이 값을 대조하지 않는다. 현재 sb 코드에서 source_hash를 실질적인 검색 검증 조건으로 사용하는 경로도 찾지 못했다.

실제 모델로 생성한 기존 임시 관리형 페이지를 읽고, 별도의 이번 검증 전용 registry에 동일 page_id와 임의 source_hash(ff…ff), ACTIVE/APPROVED를 넣었다. 일반 active 검색에서 결과1개와 VERIFIED 표시를 회수했다. [재현 결과](REGISTRY-CONTENT-BINDING-AUDIT-2026-09-10.json). 해당 표시는 레지스트리 상태에서 계산되며 본문 해시 검증 완료를 뜻하지 않는다. 이 실험은 registry 쓰기 권한을 가진 검증자가 만든 상태이며, 비인가 사용자가 승인 상태를 변경했다는 증거가 아니다.

JARVIS scoped 읽기의 claim/record digest/세대 fence와 별개의 일반 검색 표면이다. 이번 결과로 scoped 권한 검사가 우회됐다고 주장하지 않는다. 운영 레지스트리는 변경하지 않았다.

## 구현 전 필요한 결정과 순서

1. 승인 대상의 식별을 page_id뿐 아니라 provider/vault·committed blob 또는 generation과 결합한다. 기존 source_hash 필드의 의미를 임의로 재정의하지 않고 현재 저장 자료와 계약을 대조한다.
2. staging에서 외부 승인 행을 먼저 쓰는 방식은 보류한다. 세대에 포함한 상태와 공개 후 재생성 가능한 projection 중 기존 복구·철회 모델에 맞는 방식을 선택한다.
3. 정정 후 과거 승인 자동 승계, 같은 page_id의 다른 저장소, publication 실패, 삭제·복원 재유입을 함께 검증한다. 검증 기준을 충족하지 않은 예전 행은 새 본문 승인의 증거로 자동 전환하지 않는다.
4. 일반 registry 승인 표시와 사실/본문 검증·JARVIS 작업 증거를 UI/API에서 구분한다. 기존 frozen MCP 응답의 필드나 해시를 임의 변경하지 않는다.

이번 턴에서는 이 연결을 구현하거나 기존 APPROVED 행을 일괄 수정하지 않았다. 기본 경로에 사람 승인 단계를 추가하는 제안도 아니다. 기존 기본 자동 처리 원칙 안에서 상태와 대상 본문을 일치시키는 후속 작업이다. 전체 M1–M14와 운영 인수는 남는다.
