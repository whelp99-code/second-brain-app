# 검색 평가의 폐기 결정 노출 측정

기준 제품40d5e7f. 평가 모듈에 선택적 forbidden_page_ids를 추가했다. 실제 fixture 문서만 지정할 수 있고 gold와 겹치거나 중복된 ID는 거부한다. 기존 schema1과 Case 생성 호환성을 유지한다. overall/by_kind에 forbidden_labeled_cases와 forbidden_exposure_at_5를 추가했다. 라벨이 없으면 비율은 null이며 미측정을 0으로 표시하지 않는다. gold 회수율과 독립이므로 최신 근거를 찾았어도 과거 결정 동시 노출이 가려지지 않는다.

평가 회귀20통과/0.25초·Ruff 통과. 최신/폐기 문서2개와 질의3개인 명시적 합성 fixture를 추가하고 실제 CLI와 MCP 검색/본문 회수를 실행했다. /var/tmp/sb-korean-search-tcv1tpby, state=measured, exit0. [실측 evidence](STALE-SEARCH-PROBE-2026-09-10.json).

양쪽 결과 동일:
- '은하 백업 보관 기간': current-backup 1위, old-backup 2위. 최신 근거21일은 회수했지만 폐기된7일 문서도 노출.
- '현재 은하 백업은 며칠 보관해야 하나': 결과0. 관련 기억이 있어도 자연어 회수 실패.
- 무근거 연락처 질문: 결과0.

positive2개 recall@5=0.5, stale_decision2개 forbidden exposure@5=0.5. 전체3개 exposure=1/3. 작은 진단 표본이며 실제 사용자 한국어100–300개 품질 또는 성능 기준선으로 일반화하지 않는다. gold answer check1/selected read2, sealed fixture 읽기 불변도 확인했다.

과거 문서는 본문에 폐기라고 쓴 distractor이며 provider의 정정·삭제 요청으로 상태를 바꾼 것이 아니다. 따라서 이 결과는 자연어 검색 및 문서 수준 최신성 구분의 공백이다. 이미 검증한 삭제 tombstone 재유입 실패나 권한 누출로 해석하지 않는다. 검색어에 '폐기'가 보인다고 문서를 자동 삭제/권한 강등하는 우회는 적용하지 않는다.

다음 개선은 질의 정규화/토큰 선택과 검증된 상태 메타데이터 적용을 기존 구현에 대조하고, 같은 질의의 개선 및 무근거 오탐을 함께 측정하는 것이다. 이번 변경은 평가 계측·fixture뿐이며 제품 검색 결과는 아직 개선하지 않았다. 모델0회, 운영자료/서비스 변경과 push 없음. 실제 업무/다중 모델·운영 및 전체 M1–M14 목표 유지.
