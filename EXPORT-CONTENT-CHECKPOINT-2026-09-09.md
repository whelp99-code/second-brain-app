# OMO/GJC 파일 교체 감지와 세션 체크포인트 공통화

[Codex/Claude 체크포인트 수정](SESSION-CONTENT-CHECKPOINT-2026-09-09.md)을 OMO/GJC에도 적용했다. 기존 offset만 사용하는 OMO/GJC는 같은 크기 교체와 이미 읽은 prefix 수정을 건너뛰었다. GJC는 유효 export를 읽은 후 같은 크기의 비지원 헤더로 바뀌면 재개 시 재검사하지 않았다.

## 수정 범위

`session_checkpoint.read_session_checkpoint`가 파일별 prefix 비교·처음부터 재해석 여부·읽기 전후 동일 revision 검사·커서 보존·일반 파일 검사와 오류 이유를 공통으로 담당한다. 네 수집기는 자신의 기존 파서를 callback으로 사용한다. Codex 상태 복원, Claude native 추출, OMO 형식 검사, GJC 헤더 검사는 각 모듈에 남는다. connector registry와 MCP 계약을 바꾸지 않았다.

GJC의 새 체크포인트에서 헤더가 변경되면 start=0으로 돌아가 원래 헤더 validator가 다시 검사한다. 지원하지 않는 헤더는 `unsupported-version`, 소비 offset0으로 거부한다. live-session-store와 불완전 header/JSONL의 기존 거부·재개 검증도 유지한다. 읽는 중 변경은 그 파일의 추출 결과를 내보내지 않고 이전 커서를 보존하며 `unstable-session-file`을 반환한다.

## 검증

확장 회귀21개 중 기존 Codex/Claude10개는 통과했고 OMO/GJC11개는 수정 전 실패했다. 새 실패 범위는 교체6, 읽는 중 변경2, FIFO skip 관측2, GJC 동일크기 헤더 교체1이다. FIFO2개는 기존의 조용한 건너뛰기 대신 명시적인 skip 이유를 요구한 검사이며, 이번 이전 코드에서 FIFO 정지를 재현했다는 뜻은 아니다.

수정 후 관련 **50개 통과/0.30초**. 변경5모듈 basedpyright0오류/0경고, 전체 Ruff 통과. GJC에 기존 `# noqa: MATCH_OK` 형식 경고2개는 남아 있으며 새 실패로 집계하지 않는다. diff 검사 통과.

독립11프로세스를 실제 임시 파일에 실행했다.

| 수집기 | 독립 프로세스 | 파일 교체 후 | 재조회 | 정상 append | 추가 확인 |
|---|---:|---|---|---|---|
| OMO | 5 | new1개 | 0개 | add1개 | FIFO unreadable-session-file/exit0 |
| GJC | 6 | new1개 | 0개 | add1개 | 같은 크기의 v9 헤더 거부, FIFO skip/exit0 |

이는 프로세스 간 cursor 영속 전달·실제 rename/append/파일 유형 검증이다. 실제 OMO/GJC 앱의 현재 버전에서 자동 수집·주입을 완료했다는 증거는 아니다. 전체 회귀 결과는 최종 확인에 기록한다.

## 적용 경계와 잔여 항목

- 새 metadata 형식은 앞선 Codex/Claude와 같다. 기존 offset-only cursor는 읽되, 첫 hash 생성 이전의 동일크기 변경은 소급 판별하지 못한다.
- prefix 전체를 해시하는 추가 읽기 비용이 있다. 공통 함수로 모았다고 대규모 corpus 성능을 개선했다고 주장하지 않는다.
- 여러 root의 동일 상대 경로, 과거 누락 이력의 정책에 맞는 복구, 적대적 파일 교체의 모든 읽기 경계와 운영 적용은 남는다.
- 운영 cursor·원문·서비스·설정을 변경하거나 원장을 되감지 않았다. 재해석된 기존 앞부분의 중복 처리는 기존 원장 식별 규칙을 사용한다.
- 자비스 실제 운영, 전체 삭제·복원·native 보존·검색/GUI 품질과 M1–M14의 완료 조건을 유지한다.


## 최종 확인

전체 **1,388 passed / 2 skipped / 250.16초**, `uv run pytest -q --ignore=tests/test_embeddings.py` exit0. 선택 embeddings extra 제외. [구조화 결과](EXPORT-CONTENT-CHECKPOINT-2026-09-09.json). 집중 검사와 독립 프로세스 검사를 전체 테스트 수에 합산하지 않는다.
