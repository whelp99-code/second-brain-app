# 충돌 판정 인용 ID 검증

기준 제품 8e4ea39. 충돌 판정의 cites 배열에 입력에 없는 ID, 정상 ID와 미확인 ID의 혼합, 빈 문자열을 넣는 회귀를 작성했다. 수정 전 **3실패/6통과**로 세 경우 모두 불량 판정을 수락하는 것을 재현했다. 페이지의 실제 sources는 _pair_sources에서 가져오므로 이를 임의 원본 파일을 읽는 취약점이라고 해석하지 않는다. 다만 판정 cites에 입력에 없는 계보가 남고 정상 판정으로 완료되는 문제다.

파서에서 각 cites 값이 현재 prompt에 들어간 두 입력 ID 중 하나인지 검사한다. 미확인 ID가 하나라도 있으면 전체 판정을 invalid conflict verdict 경로로 처리한다. 누락/빈 배열은 기존처럼 비교한 두 입력으로 채우며 정상 단일 인용을 강제로 늘리지 않는다. 기존 무검증 판정 cache를 재사용하지 않도록 profile을 conflict-inputs-v4로 갱신했다. v2/v3 cache 이후 재판정과 새 cache 재사용 회귀를 유지한다.

최종 conflict/fake source update/walking skeleton **30 passed / 6.29초**, Ruff 전체·diff 검사 및 conflict 타입0오류0경고. 이번 수정 이후 전체 suite와 실제 모델은 다시 실행하지 않았다. 이전 실제 모델 응답의 c1/u1은 정상 ID였지만 이를 새 제품의 전체 모델 검증으로 확대하지 않는다.

기존 생성 conflict 페이지·supersede 효과를 자동 되돌리지 않으며 과거 영향 내용 점검은 별도로 남는다. 운영 DB·서비스·registry·타 리포 변경 및 push 없음. JARVIS 복원/실사용 업무·운영/DR 및 M1–M14 전체 목표는 미완료다.
