# 봉인 세대의 근거 레코드 의미 검색

상태: 구현 및 격리 CLI/MCP 정정·삭제·복원 검증 완료. 운영 활성화/전체 인수 완료가 아니다.

## 결정과 기존 경계

SB를 공통 기억 정본으로 유지하고 LightRAG의 검색 품질·근거·삭제 일관성 장점만 흡수한다.
기존 generation writer/pin/manifest/정정·삭제·복원과 frozen MCP 응답 필드를 재사용한다.
새 서버·queue·원문 cache·권한 엔진은 추가하지 않는다.

봉인 세대는 인용 가능한 `MemoryRecordV1` 단위로 벡터를 만든다. 페이지 전체의 의미 점수를
모든 record에 복사하지 않는다. record ID/digest는 기존 committed/prospective 바이트의
`parse_page_records` 결과이며, MCP에서 같은 세대의 record를 다시 확인해 반환한다.

벡터는 기존 `.sb/vectors.db` 안의 float32 BLOB으로 저장하고 조회는 기존 sqlite-vec의
cosine scalar와 SQLite를 사용한다. 별도 vec0 정본을 만들지 않는다. 이 방식은 이미 standalone
filtered cosine에서 사용하는 정확 거리 정렬이며, ANN이나 10만 벡터 지연 보장을 주장하지 않는다.
float32 BLOB 및 scalar 지원 근거는 [sqlite-vec 공식 API](https://alexgarcia.xyz/sqlite-vec/api-reference.html)다.

## 구현 조건

1. `[search] hybrid = true`가 명시된 writer만 벡터 생성을 시도한다. 기본 false의 기존 manifest
   의미는 보존한다. encoder/모델 불가 시 경고와 비활성 vector manifest로 lexical 기능을 유지한다.
   모델 장애가 정정·삭제를 막거나 이전 세대 벡터를 새 세대에 그대로 남기지 않도록 한다.
2. 모델/revision/dimension, record ID/digest, float32 벡터 바이트의 논리 digest를 generation
   digest에 결합한다. 실제 DB 바이트는 기존 derived inventory와 파일 검증으로 연결한다.
3. 이전 세대의 검증된 DB에서 같은 모델과 같은 record ID/digest의 벡터만 재사용한다.
   새/변경 레코드는 bounded batch로 인코딩한다. 새 세대의 원문 목록에 없는 행은 복사하지 않는다.
4. 조회는 이미 획득한 generation pin 안에서만 읽는다. 같은 DB의 generation binding·모델
   identity를 확인한다. metadata/knowledge 필터와 인용 가능한 record 선택 뒤 limit을 적용한다.
5. 기존 literal 검색과 semantic record 결과를 중복 제거/결합한다. 명시적 큰따옴표 검색은
   literal 의미를 유지한다. semantic 결과 때문에 서로 다른 record의 단어를 합쳐 답하지 않는다.
6. 실패·잘못된 벡터·DB 변경·모델 불일치, 두 reader와 writer, 정정/삭제·이전 세대 폐기·복원,
   native CLI/MCP 및 실제 질문 품질을 분리 검증한다. 합성 encoder 인수는 모델 품질이 아니다.

실제 모델의 메모리/배치 효율·한국어 회수율, 운영 활성화와 자비스 session 수명은 별도 완료 조건이다.
