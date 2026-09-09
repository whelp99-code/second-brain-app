# 검증된 백업의 접근 요구사항 복원

기준 제품 ddd7df4 이후 변경. 이전 단계는 지식 상태만 복원하므로, 살아남은 승인 기억도 사용자·프로젝트 제한 조회에서는 접근 분류가 없어 거부됐다. 이번 변경은 그 제한 조회를 복원한다.

`restore_access.read_restore_access`는 운영 journal과 봉인 백업을 먼저 검증하고 read-only SQLite snapshot에서 현재 records와 page_id/content_digest가 일치하는 접근 요구사항을 읽는다. 정제된 복원 파일의 실제 본문 digest까지 동일해야 후보가 된다. 참조 출처별 분류와 checksum을 검증하며 필요한 분류가 하나라도 없으면 페이지 분류 전체를 제외한다. `complete=False`를 True로 바꾸거나 일부 요구사항을 빼고 조회를 허용하지 않는다. 추출 후 원본 검증을 다시 수행한다.

페이지·요구사항·출처 분류 메타데이터는 현재 검증된 tombstone snapshot으로 검사한다. 삭제 대상 bytes가 있으면 분류를 복원하지 않는다. 접근 분류 값은 ASCII로 제한되어 있어 JSON Unicode escape로 실제 분류 문자열이 숨겨지지 않는다. 페이지 ID는 원문 UTF-8로 검사한다.

Ledger는 검증된 출처 식별자에 요구사항을 결합하는 `bind_source_classification`을 제공한다. 기존 수집용 `bind_source_access`는 source_item 존재 검사를 유지하고 이 공통 저장 경로에 위임한다. 동일 식별자의 상충하는 분류는 기존과 같이 거부한다. 복원은 원본 source_item이나 수집 cursor·원문을 재생성하지 않는다. 요구사항은 원본 자료의 존재나 사용자 권한을 보증하지 않으며, 현재 사용자 인증·정책 검사 책임은 기존 호출부에 남는다.

지식 상태와 접근 분류를 같은 신규 원장 transaction에 저장하고 기존 세대 봉인 검증을 사용한다. 복원 후보만 만들며 active pointer는 변경하지 않는다. 운영 journal까지 잃은 복원, 원본을 증명하지 못하는 백업의 상태 승계는 계속 보류한다.

검증 기록:

- 실제 sanitizer·제한 조회·기존 source_access·restore 테스트: 20 passed / 33.19초. 같은 owner/project/policy 허용, 각각 다른 값 거부, 삭제 내용 재검색 없음, 미검증 추가 문서 승격 없음.
- 실제 봉인 세대 기반 정상·incomplete·출처 누락·본문 변경·삭제 메타데이터·원장 변조: 6 passed / 1.21초.
- Ruff 전체 통과, restore_access/restore 타입 0오류·0경고. ledger 포함 타입 검사는 0오류·기존 knowledge 읽기 구간 등 7경고가 남는다.
- 전체 suite: `TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py` — **1,674 passed, 2 skipped / 435.36초**. 실행 중 제품·테스트 소스 변경 없음. [원본 로그](RESTORE-ACCESS-FULL-2026-09-10.txt). 선택 embeddings extra 테스트는 명시적으로 제외했다.

남은 인수: 실제 JARVIS 인증 transport에서 복원 세대 소비, 현재 철회/정책과 복원 상태의 조합, 운영 설치와 사용자 작업 기반 여러 에이전트 검증, 운영 journal 소실 DR 및 통합 계획 M1–M14. 이번 제한 조회 검증은 Python의 실제 봉인 페이지 읽기·scope 검사이며 native 에이전트의 실업무 완료 증거가 아니다. 운영 DB·서비스·공용 registry 변경 및 push 없음.
