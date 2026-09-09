# Codex/Claude 세션 파일 교체 시 커서 유실 수정

기존 커서는 파일별 byte offset만 저장해 같은 크기의 새 파일이나 이미 읽은 부분의 수정을 판별하지 못했다. 새로운 내용이 기록돼도 크기가 같으면 전체를 건너뛰고, 수정 후 append되면 추가된 꼬리만 수집했다. 자비스/공통 기억의 수집 누락 원인이다.

## 수정

- `sb/connectors/session_checkpoint.py`에서 이미 읽은 prefix의 SHA-256을1MiB 이하 청크로 계산한다. Codex/Claude 커서에 offset과 함께 `__sb_session_prefix_sha256_v1__` metadata를 저장한다. 내용이 다르면 해당 파일을 처음부터 다시 해석한다.
- 파일 읽기 전후 device/inode/크기/mtime/ctime을 비교한다. 변경 중이면 그 파일에서 추출한 행을 버리고 기존 커서를 유지해 다음 스캔에서 재시도한다. `unstable-session-file`로 관측된다.
- 경로/파일 읽기 오류는 `unreadable-session-file`로 보고하며 커서를 전진시키지 않는다. 파일의 크기만으로 내용의 동일성을 판단하지 않는다.
- 체크포인트는 일반 파일만 허용하고 nonblocking/no-follow descriptor로 읽는다. 구현 중 `.jsonl` FIFO에서 새 hash 코드가 대기하는 회귀를 실제 자식 프로세스에서 재현해 수정했다. 전체 검사를 중단한 뒤 수정본으로 다시 시작했다.

## 검증과 범위

- HEAD의 이전 코드와 올바른 Codex session header를 사용해 두 수집기×동일크기 덮어쓰기/rename/수정 후 append의6개 누락을 재현했다. 최초 테스트의 Codex3개 실패에는 fixture header 누락이 포함돼 있었으므로 이6개는 별도 기준선 재현 결과다.
- 집중34개 통과(0.26초): 새10개(교체6, 읽는 중 변경2, FIFO2), 기존 부분기록/native Claude/기존 세션 수집 검사. Ruff 전체 통과, 변경3모듈 basedpyright0오류/0경고.
- 실제 임시 파일을 사용한 독립8프로세스에서 처음old→동일크기 rename후new→재조회0→정상append add를 확인했다. 추가 독립2프로세스에서 두 수집기의 FIFO 즉시 skip/exit0을 확인했다. sleep을 테스트 동기화 수단으로 쓰지 않았다.
- 중단한 전체 검사:468통과/1skip/122.24초에서 SIGINT, exit2. 완료 검사로 합산하지 않는다. 최종 전체 결과는 아래 최종 확인에 기록한다.
- prefix 재검사 비용: 로컬64MiB 파일을 두 번 해시하는 단일 warm 측정0.08035초. 전체 수집기·여러 원본·cold storage·p95 성능 수치가 아니다. 해시를 위해 prefix 전체를 읽는 비용은 추가된다.

## 호환성과 남은 항목

기존 숫자 offset 커서는 읽을 수 있다. 다만 과거 해시가 없으므로 **처음 새 체크포인트를 만드는 시점 이전의 동일크기 변경은 소급 판별하지 못한다.** 이미 건너뛴 이력은 별도 복구 정책·삭제/중복 검사를 거쳐야 한다. 운영 커서를 일괄 되감거나 과거 자료를 자동 재수집하지 않았다.

변경된 파일을 다시 해석할 때 변하지 않은 앞부분도 adapter 출력에 포함될 수 있다. 기존 원장/내용 식별에 따른 중복 처리를 재사용하며, adapter 자체가 모든 기록을 정확히 한 번만 출력한다는 보장은 하지 않는다. 연속으로 쓰이는 파일은 안정된 스캔까지 수집이 지연될 수 있다. 실제 수집 중 변경은 skip 이유로 확인할 수 있다.

이 수정은 Codex/Claude에 적용했다. OMO/GJC 동일크기 교체, 여러 root의 같은 상대 경로, 적대적 파일 교체의 전체 읽기 경계, 대규모 corpus 비용 인수는 별도 남은 범위다. 운영 서비스·설정·개인 원본·기존 cursor를 변경하지 않았다. 실제 모델 API를 재호출한 시험이 아니라 독립 수집 프로세스/실제 파일 I/O 검증이다. 전체 M1–M14를 완료 처리하지 않는다.


## 최종 확인

수정 후 전체 **1,377 passed / 2 skipped / 238.71초**, `uv run pytest -q --ignore=tests/test_embeddings.py` exit0. 선택 embeddings extra는 제외했다. [구조화 결과](SESSION-CONTENT-CHECKPOINT-2026-09-09.json). 중단된 검사와 집중 검사는 전체 수에 합산하지 않는다.
