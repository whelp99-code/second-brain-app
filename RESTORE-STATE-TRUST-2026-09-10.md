# 복원 원장의 승인·접근 분류를 신뢰할 수 있는 경계

기준 제품 0712c67. 제품 변경 없이 실제 restore sanitizer에 상태 원장을 포함한 아카이브를 입력하는 테스트를 추가했다.

## 확인한 계약 한계

RestoreArchiveManifestV1은 파일 inventory와 source generation ID/digest를 담지만, 별도 source 상태 증명이나 그 원장의 현재 본문별 승인·접근 분류를 검증하는 계약은 아니다. builder는 로컬 아카이브 파일로 inventory를 다시 계산할 수 있다. GenerationRestoreSanitizer는 provider ID, 파일 digest 목록, 현재 tombstone chain/read fence를 검사하며 파생 SQLite를 제거한 콘텐츠로 비활성 후보를 만든다. 따라서 아카이브가 자체적으로 계산한 해시만으로 내부 상태를 승계하면 안 된다.

## 실제 검증

기존 restore fixture의 정상 문서에 대해 정확한 본문 digest를 가진 ACTIVE/APPROVED 행과 source_access/PageAccess(complete=True)를 archive/.sb/ledger.db에 기록했다. 파일 mode를 맞추고 archive manifest도 다시 계산했다. 실제 sanitizer가 이를 받아 비활성 후보를 만들더라도 bound state는 투영되지 않고, active 검색 결과는 없으며 정상 문서는 reference UNVERIFIED로 회수된다. classified_page도 접근을 거부한다. 현재 활성 세대는 바뀌지 않는다.

접근 거부는 재생성된 원장에 page_access 테이블 자체가 없어서 MEMORY_ACCESS_UNAVAILABLE인 경우와 행이 없는 UNCLASSIFIED인 경우를 모두 허용한다. 첫 테스트는 오류명을 UNCLASSIFIED 하나로 가정해 실패했다. 요구사항은 승인되지 않은 접근의 거부이므로 두 거부 코드를 검사하도록 수정했으며 제품 접근 검사는 변경하지 않았다.

초기 관련 restore/authority/span 실행은 **25 passed / 1 failed / 29.90초**(위 오류명 기대값). 수정 후 실제 restore integration **2 passed / 5.01초**. Ruff 전체·diff 통과. 26개 전체가 최종 재실행 통과했다고 합산하지 않는다.

## 후속 구현 판단

아카이브의 SQLite 또는 frontmatter를 그대로 승인/접근 근거로 복사하는 방식은 보류한다. 정상 복원에서 상태를 회수하려면 source 세대의 검증된 원장·manifest를 독립적으로 검증하고, sanitized 결과의 정확한 본문과 일치하는 상태 및 접근 요구사항만 결합하는 형식이 필요하다. 삭제·정정으로 본문이 달라진 경우와 외부 철회/정책 revision도 구분해야 한다. 기존 source generation이 소실된 DR에서도 검증 가능한 보관 근거를 포함해야 하며, 현재 활성 세대가 남아 있는 경우만 해결했다고 복원 전체 완료로 보지 않는다.

새 사람 승인 gate·임의 계약 예외는 추가하지 않았다. 실제 JARVIS 세션, 복원 구현·최신 설치·실제 업무·운영 및 M1–M14는 남는다. 운영 DB·서비스·공용 registry 변경과 push 없음.
