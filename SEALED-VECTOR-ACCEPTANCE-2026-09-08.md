# 공통 기억의 봉인 의미 검색 — 구현 및 인수

제품 커밋: `cbb910d`. 전체 **893 passed / 2 skipped, 113.42초**, 집중 **50 passed / 1 skipped, 13.56초**. Ruff 통과, 변경 파일 타입 오류·경고 0. [구조화된 증거](SEALED-VECTOR-ACCEPTANCE-2026-09-08.json).

세컨드브레인 기반을 유지한다는 [자비스 인계](../Orca-JARVIS/docs/second-brain-oss-absorption-handoff-2026-09-07.md)를 기존 구현과 대조했다. 이번 변경은 LightRAG에서 참고한 근거 연결 검색과 파생 데이터 일관성을 기존 generation/SQLite/MCP에 적용한다. 외부 OSS 코드 복사·패키지 설치·별도 서버 도입은 없다. [사전 ADR](SEALED-VECTOR-ADR-2026-09-08.md)의 경계를 따른다.

## 동작 판정

기존 봉인 세대는 vector enabled=0이 고정되어 있어 hybrid 설정만으로 공통 MCP의 의미 검색을 사용할 수 없었다. 이제 명시적으로 켠 writer가 새 세대를 생성할 때 인용 가능한 기억 레코드의 벡터를 봉인하고, CLI/HTTP 검색 및 MCP schema 4/5의 근거 레코드 선택에 연결한다. 기본 설정은 false다.

격리된 두 실제 MCP 프로세스와 실제 CLI의 정정→검색→삭제→검색 및 각각의 백업/별도 경로 복원은 통과했다. **실제 모델의 한국어 회수 품질, 운영 활성화, 자비스 세션 자동 주입 완료는 아니다.**

## 수정·개선 내용

| 문제 | 변경과 검증 |
|---|---|
| 관리형 세대의 의미 검색 미연결 | Config의 엄격한 TOML bool을 writer·요청 처리·CLI/HTTP/MCP 검색에 전달. 기본 false 유지 |
| 페이지의 의미 점수를 모든 근거에 적용하면 엉뚱한 인용 가능 | `MemoryRecordV1` 단위로 인코딩. 같은 세대의 실제 record ID/digest/전체 본문을 다시 대조한 뒤 MCP 반환 |
| 벡터가 원문 세대와 따로 움직임 | 모델/revision/dimension·레코드·벡터 바이트 digest를 세대 논리 manifest에 결합. 기존 파생 파일 inventory가 실제 DB 바이트를 검증 |
| 매번 전체 레코드 인코딩 | 검증된 이전 세대에서 모델과 record ID/digest가 모두 같은 벡터만 재사용. 신규 레코드는 최대 64개 배치 |
| 정정·삭제 때 이전 벡터 잔존 위험 | 현재 세대 원문 목록으로 새 DB 구성. 없어진 레코드는 복사하지 않으며 정정/삭제의 기존 writer·폐기 절차 적용 |
| 모델 장애가 삭제를 막거나 오래된 검색을 유지 | 예상 가능한 모델 부재·잘못된 수/NaN/zero/overflow·identity 변경은 경고와 깨끗한 disabled DB로 처리. 이전 레코드 벡터를 유지하지 않음 |
| 검색 후 필터로 후보 수 부족·범위 섞임 | 기존 종류/상태/날짜/knowledge 필터를 거리 정렬과 limit 전에 적용. 이 필터를 프로젝트 권한으로 해석하지 않음 |
| SQL 인자 크기 및 입력 인용 문제 | UTF-8 hex 값과 float32 BLOB의 SQL을 임시 스트림으로 전달. 읽기 전용 SQLite CLI 사용 |
| 다른 모델의 query vector·변경된 DB 사용 | 모델 identity 일치 검사와 조회 전후 봉인 파일 검증. 모델 장애는 lexical fallback, 파일 무결성 실패는 오류 |
| 정확 문구 의미 훼손·MCP 중복 record | 큰따옴표 질의는 literal만 사용. 의미/문자열 결과는 record 기준 RRF 결합과 중복 제거 |

주요 소스는 `sb/generation_vectors.py`, `sb/sealed_vectors.py`, `sb/memory_search.py`다. public MCP 응답 필드는 바꾸지 않았다. 검색 hit에 추가한 record 필드는 내부용이며 기존 `SearchHit.as_dict()` 형식은 유지한다.

## 검증과 실패 이력

최종 검증 수치와 제품 소스 해시는 같은 이름의 JSON에 기록한다. 집중 검사에는 실제 SQLite 확장 실행과 optional embeddings 검사를 포함한다. 테스트용 encoder는 1,024차원의 결정적 벡터를 반환하며 실제 모델 다운로드/외부 호출은 하지 않는다.

전체는 리포 표준 `pytest -q --ignore=tests/test_embeddings.py`다. 집중은 embeddings·새 generation/search/MCP 검사·기존 lifecycle의 hybrid false/true를 포함하며 skip은 실제 모델 opt-in smoke다. 중복되는 전체/집중 수를 합산하지 않는다.

- 증거 디렉터리: `/var/tmp/sb-sealed-vector-nmf0lt2a`, 결과 `result.json`의 state=passed.
- 두 MCP 프로세스가 처음에는 같은 generation과 기억을 회수한다.
- 단어 자체가 없는 `일정` 검색으로 `회의는 월요일`의 실제 cited record를 회수한다.
- 기존 요청 계약으로 CLI `apply-requests --once`를 실행해 `다음 만남은 수요일`로 정정하고 state=proved를 확인한다.
- 새 검색에서 이전 내용을 제외하고 정정 내용을 회수한다. 같은 상태의 백업을 별도 경로로 복원해 다시 회수한다.
- 동일 계약으로 삭제 후 state=proved, 새 검색과 삭제 후 백업 복원에서 이전/정정 내용이 모두 사라지고 무관한 보존 레코드는 남는다.
- 각 변경 뒤 실제 CAS 인용 감사가 통과하며, 인수 전후 제품 소스 SHA-256이 같다.
- 두 reader는 서로 다른 실제 프로세스지만 이 인수의 질의는 변경 완료 경계에서 수행한다. 동시 query/writer 부하를 이 실행의 증거로 주장하지 않는다. 기존 reader 잠금/종료/폐기 검사는 전체 회귀에 포함한다.

첫 native 시도는 검증 도구가 다른 스레드에서 SQLite connection을 사용해 실패했다. 두 번째는 도구가 CLI 필수 인자 `--once`를 빠뜨려 실패했다. 수정 후 세 번째가 통과했다. 제품 실패로 숨기거나 최초 실행을 통과로 계산하지 않는다.

개발 중 lifecycle 검사의 SQLite context manager가 connection을 닫지 않아 reader drain이 막혔다. 테스트를 명시적 close로 수정했다. 변조 검사는 봉인된 0400 파일에 직접 쓰려다 PermissionError가 났으며, 소유자의 chmod 후 변경을 주입해 무결성 거부를 검증하도록 수정했다.

## 남은 수정·개선·고도화 목록

| 우선 | 항목 | 이유와 완료 기준 |
|---|---|---|
| P1 | 실제 한국어 검색 평가 | 실제 질문 100–300개와 실제 임베딩으로 lexical 대비 근거 Recall@k·정정 전 내용 노출·무정답률·지연 비교. 합성 벡터 통과로 품질 개선을 주장하지 않음 |
| P1 | 무정답과 낮은 관련성 처리 | 현재 cosine은 가까운 후보를 반환하며 최소 유사도 기준이 없다. 삭제 후 무관한 보존 record가 반환되는 것은 가능하다. 실제 평가로 임계값/혼합 점수 정책을 결정 |
| P1 | 자비스 전달 수명 C6–C8 | 기존 reference/context 기능을 실제 session 전달 receipt·중복 방지·compaction·후속 정정/삭제 무효화에 결합. 호출자가 쓴 성공 문자열을 모델 수신 증거로 쓰지 않음 |
| P1 | 공통 기억의 접근 범위 | owner/read fence와 knowledge 필터만으로 프로젝트 권한 격리를 주장할 수 없음. 분류·접근 계약을 search/page/target/export에 일관되게 적용 |
| P1 | 실제 운영 전환·복구 | 실제 설정/클라이언트/UI/서비스에 대한 인수와 새 호스트 DR. 이번 격리 실행은 운영 배포가 아님 |
| P2 | 임베딩 배치 비용 | 64개 배치가 Python 입력을 제한하지만 기존 remote encoder는 호출마다 모델 프로세스를 실행. 최초 대량 생성 시간·peak RSS 측정 후 개선 |
| P2 | 검색 규모·가시성 | 정확 cosine scan과 registry CTE는 ANN이 아님. 대규모 p95/메모리 측정, enabled/disabled/모델 불일치 상태의 운영 화면 가시성 보강 |
| 보류 | 자동 결과 수집·세션 주입 | 검증된 원본 상태·차단/철회 계보와 실제 전달 수명 계약 전까지 자동화하지 않음 |
| 보류 | 그래프 DB·새 Proxy·추가 기억 서버 | 측정된 필요 없이 정본과 운영 경로를 늘리지 않음 |
| 보류 | 관측 불가 임시 DB 자동 삭제 | 이전 보고서의 열린 FD 관측 한계 유지. 광범위 glob 삭제로 물리 폐기 완료를 주장하지 않음 |

Tencent식 공통 인터페이스는 기존 MCP와 provider를 유지하고, code-brain식 제한된 문맥 공급은 기존 자비스 reference 예산을 재사용한다. memory-bank식 세션 재사용은 위 수명 계약이 남는다. 개발 결정의 정본은 dev-wiki/Git로 유지한다. 인계의 네 OSS를 한꺼번에 설치하거나 에이전트별 기억 DB를 추가하지 않았다.

운영 vault·서비스·자비스 소스·DB migration·모델 설정은 변경하지 않았다. 기존 B4–B8의 전체 미완료 조건은 계속 유지한다.
