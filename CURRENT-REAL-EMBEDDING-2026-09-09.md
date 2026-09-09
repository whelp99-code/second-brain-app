# 현재 실제 임베딩 검증 — 2026-09-09

기본 캐시에 모델이 없다는 직전 관측에 이어 이전 검증 문서를 대조했다. `/var/tmp/sb-bge-evaluation-hf/hub/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181`이 현재 존재한다. 이 경로를 HF_HOME으로 명시하고 HF_HUB_OFFLINE=1/TRANSFORMERS_OFFLINE=1, OMP_NUM_THREADS=2/MKL_NUM_THREADS=2로 실행했다. 기본 캐시 가용성과 명시적 개발 캐시 가용성을 구분한다.

1. SB_LIVE_EMB=1 uv run pytest -q tests/test_embeddings.py -k live_warmup: 1 passed / 30 deselected / 33.55초. 실제 모델 초기화·색인·한글/영어 비어 있지 않은 검색을 확인했다.
2. PYTHONPATH=. .venv/bin/python scripts/sealed-vector-acceptance.py --real-model: exit 0. 실제 모델과 별도 MCP/CLI 프로세스의 초기 검색→정정→삭제→정정/삭제 백업 복원 검사 통과. 원문 ‘회의는 월요일’이 ‘다음 만남은 수요일’로 바뀌고 삭제 후 해당 기록은 사라졌다. 비용 기록은 유지됐다. CLI correct/forget 모두 PROVIDER_PROVED이며 최종 CLI 검색도 통과했다.

원시 결과: `/var/tmp/sb-sealed-vector-o33h1o_x/result.json`, 저장소 동명 JSON에 전체 결과 보존. 소스 변경 없이 현재 제품을 검사했다. 모델 다운로드·운영 활성화·운영 설정 변경 없음.

남는 품질 문제: 삭제 후 ‘일정’ 질의에 관련 없는 ‘비용은 만원’이 검색 후보로 반환된다. 따라서 이 결과는 삭제 일관성과 실제 encoder 실행을 증명하며, 근거 부족 판단 또는 한국어 100~300문항의 정답 품질을 증명하지 않는다. 실제 에이전트 자동 주입·전체 물리 사본 삭제·운영 전환도 별도 인수 대상이다.
