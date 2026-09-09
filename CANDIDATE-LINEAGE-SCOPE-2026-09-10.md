# 같은 본문, 다른 작업 출처의 접근 분리

현재 구현 대조: `remember_page.materialize_remember`는 CAS 본문을 공유하지만 candidate ID와 content hash로 페이지를 구분하고 원본 출처를 memory-candidate:<candidate_id>로 남긴다. `memory_records.parse_page_records`는 이 출처 문자열의 SHA256을 source_identity_full로 제공한다. 표시 label Second Brain 자체는 작업 계보가 아니다.

JARVIS `memory-candidate-material.ts`의 source digest는 source metadata와 source references를 결합한다. SB scoped preparation/request는 candidate/classification/source digest와 요청 바인딩을 검증한다. 따라서 원작업의 의미와 성공 근거는 JARVIS 정본에서 확인해야 하며 SB 본문이나 generic label로 대체하면 안 된다. 이번에는 원작업 resolver API를 임의 추가하지 않았다.

새 봉인 세대 회귀: 동일한 문장을 candidate A/project A와 candidate B/project B로 저장하고 실제 scoped search를 실행했다. 각 scope는 자기 기억1건만 회수, source_identity_full은 각 원래 candidate 출처 해시와 일치, page source requirements도 각 scope와 일치했다. 텍스트는 같지만 page ID/record ID가 다르고, 양쪽 scope를 가진 요청은2건, CAS blob은1개였다. 본문 중복 제거가 출처/권한 합병으로 이어지지 않음을 검증했다.

관련 `tests/test_scoped_remember_page.py tests/test_remember_page.py tests/test_scoped_search.py`:13passed/4.27초. Ruff전체/diff통과. 제품 수정 없음. 합성candidate와provider library검사이며 실제 사용자 작업ID→검증결과→candidate의 운영 계보 인수는 아직 아니다.

M4 다음 완료 증거는 실제 업무의 원문 및 검증 ID를 기준으로 이 candidate digest 연결을 양쪽에서 재조회하는 것이다. 사용자에게 요청한 실제 업무 사례는 아직 제공되지 않았다. 운영 전환·native 세션 전체 수명·M1–M14 범위는 유지한다.
