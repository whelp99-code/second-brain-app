# 관리형 지식 상태의 세대 결합 구현 경계

기준 소스75a62af. 이 문서는 구현 경로 선택과 확인한 근거다. 승인 상태 연결 구현 완료 또는 배포 승인 문서가 아니다.

## 새로 확인한 경계

- generation_walk.surface_files는 기본적으로 최상위 .sb를 순회하지 않는다. GenerationStore._copy_allowed는 그 결과로 다음 세대 원본을 복사한다.
- _content_rows 역시 일반 콘텐츠 목록을 사용하므로 .sb의 임의 knowledge-registry.sqlite를 넣어도 콘텐츠 digest에 포함되지 않는다.
- generation_staging.copy_operational_ledger는 ledger.db를 SQLite backup으로 복사하고 runs.log·compiled marker를 별도로 복사한다. 임의 registry 파일은 복사하지 않는다.
- generations의 파생 원장 재구성은 기존 원장을 backup한 뒤 generation_meta/records를 재생성한다. 따라서 기존 원장에 새 내부 상태를 두는 경로를 재사용할 수 있다.
- generation_access.access_bound_ledger_digest는 source_access/page_access의 정규화된 행을 검증하고 기존 logical digest에 결합한다. 임의 새 테이블은 자동으로 이 해시에 포함되지 않는다.

따라서 staging에서 외부 registry를 갱신하는 방식과, .sb에 registry 파일만 추가하는 방식을 모두 제외한다. 전자는 공개 전 외부 상태 노출, 후자는 다음 세대 복사 및 검증 해시 누락을 해결하지 못한다.

## 채택할 구현 단위와 완료 기준

1. 운영 원장에 페이지별 본문 digest와 컴파일 상태를 저장하는 타입·테이블을 정의한다. 기존 source_hash 필드 의미를 바꾸거나 과거 승인 행을 일괄 승격하지 않는다. 페이지 ID는 실제 wiki/daily/conflicts 경로의 canonical ID를 사용한다.
2. 기록 시점은 실제 적용된 PageSpec의 vault 쓰기 이후이며, proposal이나 쓰기 실패를 승인 상태로 기록하지 않는다. 동일 본문 재실행은 중복 상태를 만들지 않는다. 원장 transaction/세대 publication 경계를 따른다.
3. 정규화된 상태 행을 generation ledger digest의 새 결합 규칙에 포함한다. 새 행이 없는 기존 세대는 기존 digest를 유지한다. build와 read verifier가 같은 규칙을 사용하며 행/본문 불일치는 verified로 승격하지 않는다.
4. 일반 sealed lexical/vector 검색의 상태 조회를 같은 세대·본문에 결합한다. 외부 registry의 철회/비활성 상태를 내부 자동 상태가 덮어쓰지 않도록 우선순위와 범위를 명시한다. 이 부분은 구현 전에 기존 관리 명령·검색 scope 회귀와 함께 대조해야 한다.
5. 정정된 본문에는 과거 digest의 상태를 승계하지 않는다. 삭제된 페이지는 결과에 나오지 않으며 복원/재색인에서도 tombstone와 같은 세대 검증을 거친다. 오래된 페이지 ID만 맞는 외부 행으로 검증 표시를 만들지 않는다.
6. 추가 사람 승인 단계를 기본 경로에 넣지 않는다. 현재 자동 처리 원칙을 유지하면서 승인 대상과 근거를 고정한다. 기존 frozen MCP 필드·해시 검사 완화나 임의 버전 예외를 추가하지 않는다.

필수 인수: 신규 컴파일→별도 프로세스 조회, 동일 본문 재실행, 본문 교체/동일 ID, 상태 행 변조, 실패한 publication, 공개 전/후 SIGKILL, 정정·삭제·복원, 외부 철회와 충돌, lexical/vector 동등성. 먼저 관리형 내부 상태/해시를 구현하고 검색 연결을 이어간다.

## 이번 확인

기존 generation access/walk/sealed search **46 passed / 2.81초**, 해당 모듈 Ruff 통과. 새 지식 상태 구현을 테스트한 결과가 아니라 기존 확장 경계의 회귀 확인이다. 제품 소스는 변경하지 않았다. 운영 저장소·서비스·공용 registry 변경 없음. 관리형 상태 연결과 최신 설치·실제 업무 공유·운영 및 M1–M14는 미완료다.
