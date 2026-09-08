# 벡터 재생성의 기존 DB 보존과 대량 SQL 수정

최신 병합 상태: [100회 쓰기 최종 통과](WRITE-CYCLE-ACCEPTANCE-2026-09-08.md) 후 원 작업공간 `49442bc`에 반영했다. 아래 병합 대기 표시는 당시의 검증 이력이다.

상태: **격리 제품 구현·전체 회귀·실제 CLI 인수 통과, 원 작업공간 병합 대기.**
제품 커밋 `5d25d3a`.
작업공간 `/var/tmp/sb-korean-query-work`, 브랜치 `codex/korean-query-consistency-20260908`.
기존 [하이브리드 필터 수정](HYBRID-FILTERS-2026-09-08.md)의 후속이며 운영 hybrid는 활성화하지 않았다.

## 재현한 결함과 수정

초기 네 테스트가 모두 실패했다. 로그 `/var/tmp/sb-vector-rebuild-before.log`.

| 문제 | 재현된 영향 | 수정 결과 |
|---|---|---|
| encode 전에 vectors.db 삭제 | 모델 실패로 기존 검색 DB가 사라짐 | 새 임시 DB의 인코딩·SQL·검증 성공 뒤 원자적 교체 |
| 전체 SQL을 단일 argv로 전달 | 48개 추가 section에서도 E2BIG / Argument list too long | 생성 SQL을 익명 임시 파일에 순차 기록하여 SQLite stdin으로 전달 |
| encoder 결과 수 검증 없음 | IndexError와 기존 DB 소실 | 개수·1024차원·유한값·float32 norm 범위·identity 검사, 기존 DB 보존 |
| 봉인 root 직접 재생성 허용 | generation manifest 밖에서 vector 파일 변경 가능 | generation.json 존재 시 독립 rebuild 거부 |

추가로 Git 경로 열거 실패를 빈 인덱스로 오인하지 않게 했다. 처음 캡처한 commit object ID로 모든
본문을 읽고 embedding_meta.git_head에 기록한다. 생성 중 HEAD가 바뀌면 게시하지 않고 재시도를
요청한다. 기본 committed_paths/committed_text 호출은 기존 HEAD 동작을 유지한다.

## 저장 및 읽기 경계

- `sb/embeddings.py`는 모델·chunk 수집·SQL 생성·행 수/quick_check 검증을 맡는다.
- `sb/vector_rebuild.py`는 writer 잠금과 임시 DB/교체/동기화를 맡는다. 역방향 import를 없앴으며
  기존 sb.embeddings.EmbeddingUnavailable import를 재노출해 유지한다.
- private vectors.lock에 nonblocking flock을 잡는다. 심볼릭 링크·공유 권한·다중 hardlink 잠금은
  거부한다. 두 번째 writer는 명시적 오류이며 reader는 잠금을 기다리지 않는다.
- 새 DB 파일 mode는 0600이다. 생성·transaction commit·quick_check/행 수 확인 뒤 파일 fsync,
  같은 디렉터리 os.replace, 부모 디렉터리 fsync 순서로 게시한다.
- SQL 하위 프로세스에 writer descriptor를 전달한다. 부모가 종료돼도 쓰는 자식이 살아 있으면
  그 descriptor가 잠금을 유지한다. 일반 실패는 자신이 만든 DB와 journal만 정리한다.
- 이미 열린 SQLite reader는 교체 전 파일을 계속 읽고, 새 reader는 완성된 새 파일을 연다.
  별도 queue/서버/권한 엔진이나 검색 정본은 추가하지 않았다.

SQLite CLI stdin은 문자열 안의 CRLF도 LF로 바꾼다는 것을 실험으로 확인했다. 따라서 기존
run_vec_sql의 소규모 argv 경로는 유지하고, 재생성 전용 SQL의 모든 동적 문자열을 UTF-8 hex
CAST로 만든다. 한글·따옴표·CRLF·단독 CR·tab·NUL·CLI 명령처럼 보이는 본문의 바이트가 SQL
전달 과정에서 보존된다. 기존 Markdown section 분리의 줄바꿈 정규화는 별개이며 이번에 변경하지 않았다.

## 검증

- 집중 **83 passed / 1 skipped (8.17초)**: 새 재생성 검사, 기존 embeddings, hybrid filters,
  search. `/var/tmp/sb-vector-rebuild-focused.log`. Skip은 실제 모델의 opt-in smoke다.
- 표준 전체 **797 passed / 2 skipped (217.71초)**, `/var/tmp/sb-vector-rebuild-full.log`.
  집중 검사와 일부 중복이며 합산하지 않는다.
- 새/변경 embeddings·vector_rebuild·테스트 타입 **0 errors / 0 warnings**.
  `/var/tmp/sb-vector-rebuild-types.log`. 전체 search.py 검사에는 변경하지 않은 기존 위치의 경고
  6개가 있으며 오류는 0개다. `/var/tmp/sb-vector-rebuild-search-types.log`. 전체 Ruff와 diff check 통과.
- 실제 SQLite transaction을 연 reader가 재생성 후에도 이전 3행을 읽고 새 연결은 4행을 읽었다.
- encode/SQL/사후 검증/원본 열거 실패·원본 commit 변경에서 기존 DB 바이트가 유지됐다.
- 실제 프로세스의 os._exit(17) 후 기존 검색 성공, 다음 rebuild의 잠금 획득과 정상 완료를 확인했다.
- 실제 CLI 하위 프로세스에서 **131 vectors** 재생성 및 cosine 검색 성공. 최초 48 sections
  E2BIG 재현보다 큰 입력이다. 모델만 결정적 fixture로 주입하고 CLI·Git·SQLite는 실제 코드다.
- 별도 실제 CLI 5시나리오 재검증: flag off, 필터/limit, candidate, 문자열 필터, 정정 전 vector
  제외 모두 통과. `/var/tmp/sb-vector-rebuild-cli.log`, `/var/tmp/sb-hybrid-filter-clg3fed5/result.json`.

집중 재현/인수는 optional sqlite-vec가 설치된 앱 Python에 명시적 PYTHONPATH로 격리 제품을
연결했다. 새 의존성/모델 설치는 없으며 모델 품질이나 10만 벡터 성능의 증거로 계산하지 않는다.

## 잔여 및 보류 판정

| 우선순위 | 남은 항목 | 완료 조건 / 보류 이유 |
|---|---|---|
| P1 | 봉인 세대와 vector binding | manifest의 파일/모델 identity와 같은 reader pin으로 조회하고 삭제·정정·백업/복원까지 검증 후 운영 활성화 |
| P1 | Git/registry/vector 동시 전환 | 현재 HEAD 재확인과 replace는 전역 transaction이 아니다. 게시 직전 외부 commit/registry 변경까지 막는 세대 수명 계약 필요 |
| P1 | 대규모 인코딩 메모리 | SQL argv 한계만 해결했다. 모든 text/vector를 모으는 encoder API는 유지하므로 모델 상주·배치·취소/메모리 상한을 별도로 검증 |
| P1 | 강제 종료 임시 DB 회수 | 정상 실패는 정리하지만 os._exit/SIGKILL은 미게시 임시 DB를 남길 수 있다. 살아 있는 writer/child/reader 소유권을 확인한 복구 정책 필요; 무조건 glob 삭제 보류 |
| P1 | 실제 한국어 품질 | 실제 질문 100~300개, encoder와 lexical 비교, latency/memory/정답 출처 검증 필요 |
| P2 | fsync 이후 오류 관측 | replace 후 디렉터리 fsync 실패는 새 파일 게시와 오류 응답이 함께 발생할 수 있다. 운영 장애 관측/재시도 판단 검증 필요 |

봉인 구현을 다시 대조하면 `sb/generations.py`는 vector 논리 manifest를 enabled=false/rows=0으로
만들고 물리 generation_meta에도 CHECK(enabled=0)을 강제한다. 따라서 단독 rebuild 성공이나
설정 한 줄로 managed generation 의미 검색이 완성되는 구조가 아니다. 다음 구현은 이 논리·물리
계약과 읽기 pin을 함께 변경하고 기존 삭제/복원 무결성 검사를 통과해야 한다.

앞선 d174276 → 47fa507 → 9323a6d → ef3466e → 5d25d3a 순서로 병합한다.
원 작업공간의 대규모 100회 쓰기 실행이 끝나고 최종 무변경 실행·백업 복원·source hash 검사가
통과하기 전에는 sb/ 소스를 바꾸지 않는다. 현재 B4~B8 전체 완료와 운영 전환은 아직 미완료다.
