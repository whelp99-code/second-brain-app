# 공통 기억의 원본 분류 보존 — 첫 구현 단위

2026-09-09. 제품 커밋 `62b1609`. 원본 분류 저장과 실제 수집 연결을 구현했다. **사용자/프로젝트 ACL의 전체 완료가 아니며 기존 MCP 조회 범위를 제한하지 않는다.**

## 구현한 동작

`[source_access.<source id>]`의 운영자 설정에서 owner, 정렬된 projects, policy_revision을 읽는다. owner는 principal: 식별자, project는 project: 식별자이며 wildcard·중복·정렬되지 않은 목록을 거부한다. 목록은 최대64개, 빈 목록은 owner 전용 분류다. 이 값은 접근 허용 claim이나 검증된 사용자 신원을 대신하지 않는다.

새 `SourceAccess` 불변 모델과 `Ledger.bind_source_access/source_access_for`를 추가했다. source ID·URI·내용 해시를 domain-separated digest로 결합하고 분류 JSON과 분류 digest를 원장 v3의 source_access 표에 저장한다. 원문 frontmatter·제목·경로·LLM 출력에서 owner/project를 추측하지 않는다.

수집은 원본·분류·unit·cursor를 같은 기존 원장 transaction에 기록한다. 없는 원본에 분류를 붙일 수 없으며, 동일 분류의 반복 기록은 재사용한다. 동일 원본 내용에 다른 분류를 붙이면 SOURCE_ACCESS_RECLASSIFICATION_REQUIRED로 거부한다. 기존 설정과 저장된 분류가 달라지면 변경된 원본 유무와 무관하게 수집 시작 전 거부한다. 기존 분류를 수정하는 별도 승인/정정 흐름은 이번에 열지 않았다.

이전 원장은 additive v3로 이전하고 기존 source_item 구조를 유지한다. 과거 무분류 원본을 자동으로 project 자료로 지정하지 않는다. `None`은 미분류이며 이후 scoped 응답에서 project 접근 허용으로 해석하면 안 된다. 봉인 세대의 기존 SQLite 복사 경로는 이 분류 표도 보존한다.

## 함께 수정한 WAL 백업 결함

마이그레이션은 기존 DB를 shutil.copy2로 복사했다. main 파일보다 WAL의 committed 상태가 앞선 경우 백업이 최신 상태를 누락했다. 재현에서 원본 schema_meta는2지만 백업은 main 파일에 남은3으로 나타났다.

SQLite backup API로 일관된 committed snapshot을 복사하고 기존 파일 메타데이터를 보존하도록 수정했다. WAL이 열린 상태의 v2→v3 검사에서 기존 원본 행·미분류 상태·v2 백업 보존을 확인했다. 미완료 transaction이나 운영 전체 재해 복구를 검증했다는 뜻은 아니다.

## 실제 CLI 인수

별도 CLI 프로세스로 관리형 봉인 세대를 사용했다. 합성 문서 frontmatter에는 다른 owner/project를 넣고 설정에는 principal:owner/project:alpha를 지정했다.

- 최초 수집 exit0, source1개/classification1개.
- 재수집 exit0, 같은 source_ref/classification digest 유지.
- 설정을 project:beta/policy:2로 변경한 수집 exit1, 기존 분류 유지.
- 읽기 전용 immutable SQLite 연결로 봉인 세대의 결과를 확인했다.
- 실제 원문이나 운영 설정을 변경하지 않았다. 인수용 합성 문서와 임시 저장소를 사용했다.

[기계 증거](SOURCE-ACCESS-CLASSIFICATION-2026-09-09.json). 재현: `TMPDIR=/var/tmp .venv/bin/python scripts/source-access-acceptance.py`.

초기 테스트에서 source 선택을 생략해 기본 adapter까지 스캔한 실패 실행이 있었다. 해당 실행이 생성한 임시 폴더를 제거하고, 최종 테스트/CLI는 docs 원본만 명시적으로 선택했다. 원본 파일은 변경하지 않았다. 관리형 CLI 첫 시도는 active 경로 제약에 맞지 않아 거부됐으며 share/vault 경로로 수정 후 인수했다.

## 최종 검사와 이전 버전 영향

- 집중 source access/원장26통과 이후 전체 **1,104 passed / 2 skipped / 205.82초**. 명령은 `pytest -q --ignore=tests/test_embeddings.py`다.
- 최초 전체 검사는 WAL 백업 재현1개 실패/1,103통과였으며 수정 후 전체를 다시 실행했다. 두 결과를 합산하지 않는다.
- 전체 sb/tests Ruff와 diff check 통과. 변경 Python 모듈 정적 검사0오류이며 기존 pipeline.py:417의 미사용 반환값 경고1개가 남는다. 새로운 경고는 없다.
- 최종 실제 CLI 원본은 `/var/tmp/source-access-acceptance-9ucri_a4/result.json`이다.

원장 schema3는 이전 writer가 지원하지 않을 수 있다. 구버전 코드로 바꾸는 것만을 복구 절차로 안내하지 않는다. 보존한 v2 백업은 마이그레이션 전 snapshot이며 최신 삭제 이력·세대·설정까지 포함한 전체 운영 복구 인수는 별도다.

## 다음 구현과 범위

원본 분류는 저장되지만 아직 파생 record/page에 전파하거나 접근 허용을 판정하지 않는다. 다음 단위는 전체 원본의 분류를 record/page에 결합하고, 다중 원본 중 하나라도 미분류/불허라면 scoped 응답에 포함하지 않는 규칙이다. 그 뒤 자비스의 검증된 사용자·프로젝트·policy revision claim과 검색/직접 원문/target/쓰기/status/export/restore/context 경계를 함께 연결한다.

자비스 후보/remember 요청의 버전 확장과 원작업 계보는 여전히 필요하다. 운영자 source 설정을 자비스의 작업 승인 증거로 사용하지 않는다. 기존 owner MCP의 전체 조회를 이 설정이 제한한다고 안내하지 않는다. 자동 재분류·임의 project 파라미터에 의한 권한 확대는 보류한다.

native 세션/WAL/백업 수명, 다중 runtime/직접 writer와 root 정체성, 실제 앱 새 세션 재사용, 검색 평가·수집/주입·GUI·운영 복구의 목표를 유지한다. 운영 배포·서비스 재시작·push는 수행하지 않았다.
