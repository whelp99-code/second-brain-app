# 같은 내용의 다른 출처가 컴파일에서 누락되는 결함 — 2026-09-09

## 실제 재현

원장과 커서는 출처별로 분리됐지만 기존 derivation key는 unit ID·stage·prompt·model만 사용했다. unit ID는 내용 hash·span·normalizer version으로 만들어져 같은 내용의 두 출처가 같은 컴파일 키를 공유했다. 파이프라인이 첫 페이지를 완료하면 두 번째 페이지를 이미 완료된 것으로 건너뛰었다.

네 세션 형식의 기존 실제 CLI 테스트를 compile까지 확장하자 모두 실패했다. 동일 내용의 두 SourceItem과 두 cursor가 있지만 wiki 페이지는 하나였다. 이전 source-isolation 검증은 ingest까지만 검증한 것으로, 컴파일 완료를 증명하지 않았음을 명시한다.

## 수정과 검증

컴파일 derivation 입력에 `compile-page-v1:` + page_id를 추가했다. 내용 저장·unit ID·source URI는 유지하면서 페이지별 완료 상태를 분리한다. 명시적 source ID가 다른 페이지가 다른 키를 갖는다. 같은 페이지 재실행은 여전히 동일 키다. 단순 정수 객체 ID 캐시는 전체 sb 검색에서 앞서 수정한 컴파일 캐시 외에 추가 발견하지 못했다.

- 실제 CLI로 네 형식 각각 ingest→compile→compile 재시작→ingest 재시작→한 폴더 추가 ingest를 검증: 페이지 2개 생성, 재컴파일 시 페이지 bytes 불변, source별 커서 독립성 유지.
- 모호한 source 구성의 반복 실패 검사도 유지.
- compile·source isolation·memory access·page projection·walking skeleton: **33 passed / 33.58s**.
- 기존 exact PageSpec 테스트의 기대 키는 새 형식으로 갱신했다. 나머지 PageSpec 필드는 동일하다.
- Ruff 및 compile 타입 검사 통과. 전체 1,418개 통과 결과는 이 수정 전의 결과이며 이번 키 변경 후 전체 suite 재검증은 별도다.

## 적용 영향과 보류

기존 키를 삭제하거나 완료로 대입하지 않는다. 키가 바뀌므로 기존 페이지는 이후 compile에서 한 번 재처리될 수 있다. 기존 페이지 본문/인용/권한 상속 경로를 유지하고 기존 compile 호출 cap을 적용한다. 운영 배포 전 재컴파일 규모·비용·분류 보존과 새 설치 후보 검증이 필요하다. 운영 DB·서비스는 변경하지 않았다. fixture 텍스트와 FakeLLM 검사이며 실제 모델 요약 품질 검증이 아니다.
