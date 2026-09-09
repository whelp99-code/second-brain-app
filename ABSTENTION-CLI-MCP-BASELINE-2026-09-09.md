# 답변 불가 CLI/MCP 기준선 — 2026-09-09

기존 평가기는 회수한 gold 페이지의 선택된 record에 answer_span이 존재하는지, 출처와 generation이 맞는지 이미 검사한다. 중복 평가 구현을 추가하지 않고 tests/fixtures/korean_abstention_v1.json을 추가했다. 회의/비용/배포 원문 3개와 질의 4개인 합성 반례이며 실제 사용자 평가 100~300개를 대체하지 않는다. 짧은 ‘일정’은 회의와 배포 날짜를 모두 정답으로 지정했다. 서버 주소는 corpus에 없으므로 no_answer로 지정했다.

명령: HF_HOME=/var/tmp/sb-bge-evaluation-hf HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 PYTHONPATH=. uv run python scripts/korean-search-acceptance.py --dataset tests/fixtures/korean_abstention_v1.json --hybrid

실제 BGE-M3 및 별도 CLI/schema5 MCP의 4문항 평가가 exit 0으로 측정 완료됐다. 원문·선택 기록·출처 검증과 봉인 파일 불변 검사 통과. **측정 완료는 품질 합격이 아니다.**

양쪽 positive recall@5=1, hit@1=1, negative_empty_rate=0. 서버 주소 질문에 배포 날짜→회의 날짜→비용 순으로 3개가 반환됐다. CLI/MCP의 각 질문 순위는 일치했다. 검색 회수와 답변 근거 충분성을 분리해야 한다. 결과 존재만으로 답변을 생성하거나 이 작은 반례에 맞춰 임계값을 선택하는 변경은 보류한다.

원시 증거: /var/tmp/sb-korean-search-46lf51m1, 저장소 동명 JSON에 결과·순위 보존. 운영 설정/서비스/검색 기본값 변경 없음. 원작업 근거 기반 소비자 답변 검증, 실제 사용자 평가 및 전체 M1–M14는 계속 진행한다.
