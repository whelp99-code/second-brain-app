# 적용된 컴파일 본문에 지식 상태 기록

기준 소스 82b8f0a. 기존 관리형 상태 저장·세대 해시 결합에 이어 pipeline의 실제 쓰기 경로를 연결했다.

## 구현

`_commit_pages`는 Vault.write_pages의 applied_page_ids만 선택한다. 반환된 commit의 Git blob 전체 bytes를 읽고 canonical page ID와 sha256 digest에 ACTIVE/APPROVED 자동 처리 상태를 원장 transaction으로 기록한다. PageSpec의 렌더링 전 body나 작업트리에서 임의로 읽은 내용에 승인을 붙이지 않는다. 기존 외부 registry의 자동 처리 정책과 같은 상태이며 사실의 진실성·접근 권한을 새로 보증하지 않는다.

원장 연결을 두 호출부(일반 stage 결과 및 streaming compile)에 전달했다. Git blob 읽기/상태 충돌 실패는 COMPILED_KNOWLEDGE_BINDING_FAILED로 보고한다. 적용된 페이지가 없는 proposal은 기록하지 않는다. 여러 적용 상태 기록 중 실패하면 해당 transaction을 rollback한다. Git commit과 SQLite는 단일 원자 transaction이 아니며, 실패한 일반 vault에 페이지는 남고 상태만 없는 경우가 가능하다. 관리형 publication의 추가 실패 인수는 후속 범위다.

## 검증

관련 compile/managed runtime/run_all/registry/generation/walking skeleton **38 passed / 3.71초**, Ruff 및 diff 통과. pipeline 타입 검사 0 오류, 기존 registry.put 결과 미사용 경고 1개.

실제 임시 관리형 저장소를 생성해 두 차례 compile→후속 세대 publication을 실행했다. 첫째·둘째 본문 digest가 다르고 두 상태가 원장에 보존됨을 read-only SQLite로 확인했다. 사람 수정 이후 두 차례 proposal은 기존 승인 상태만 유지했다. CAS에 없는 출처를 인용한 페이지는 쓰기 실패하고 상태 0행을 유지했다.

초기 실패 fixture는 무인용 본문이 반드시 실패한다고 가정했으나 현행 Vault는 sources=[] 자체를 거부하지 않아 테스트가 실패했다. 실제로 거부하는 missing-CAS 인용으로 fixture를 수정했다. 무인용 문서를 VERIFIED로 볼 수 있는지의 검색 정책은 별도 후속 판단이며, 이번 변경으로 출처 검증이 강화됐다고 주장하지 않는다.

## 남은 일

검색은 아직 새 내부 상태를 사용하지 않는다. 다음 작업은 같은 세대·현재 본문 digest로만 상태를 조회하고 외부 철회/비활성 상태의 우선순위를 정하는 것이다. 일반 검색의 오래된 외부 승인 문제, lexical/vector 동등성, 정정·삭제·복원·publication 실패 인수, 최신 설치본과 실제 사용자 업무/다른 에이전트 회수 및 M1–M14는 남는다.

이번 운영 저장소·서비스·공용 registry 변경과 push 없음. 새 지식 상태가 있는 세대는 구버전 reader가 거부하므로 운영 활성화·구버전 rollback은 여전히 보류한다.
