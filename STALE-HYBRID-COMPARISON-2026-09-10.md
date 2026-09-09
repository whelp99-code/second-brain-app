# 최신성/무근거 질문: lexical 대 실제 hybrid 비교

제품 d709723. 기본 LexicalQuery는 literal all-terms 계약이다. '현재 은하 백업은 며칠 보관해야 하나'의 모든 토큰을 요구해 실제 본문에 없는 조사 결합어·질문어 때문에 결과0이다. 기존 정확 구문 및 cited record 검사를 무조건 OR로 바꾸지 않았다.

같은 합성3질의/문서2개에 기존 hybrid를 켜고 실제 BGE-M3 revision5617a9f61b028005a4858fdac845db406aefb181/1024차원/벡터2행으로 CLI와 MCP를 비교했다. 기본 min_similarity=-1을 유지했다. 최종 추적 없는 실행 /var/tmp/sb-korean-search-e4qcukpi, state=measured, exit0. [실측 evidence](STALE-HYBRID-COMPARISON-2026-09-10.json).

| 지표 | lexical | hybrid |
|---|---:|---:|
| positive2개 recall@5 | 0.5 | 1.0 |
| stale_decision2개 forbidden exposure@5 | 0.5 | 1.0 |
| no_answer1개 빈 결과 비율 | 1.0 | 0.0 |

양쪽 표면 결과 동일. 하이브리드는 자연어의 최신 근거를 회수했지만 폐기 문서도 함께 노출했고 연락처 질문에도 백업 문서를 반환했다. 이 결과에 따라 **hybrid 기본 활성화는 보류**한다. 단일 임계값 상향 역시 기존 SEMANTIC-ABSTENTION-COUNTEREXAMPLE-2026-09-09.md 반례를 해결하지 않는다. 후보 반환이 실제 답변 가능성을 보장하지 않는다.

실행 이력: 첫 기본 캐시 실행과 HF_HOME 지정 uv 실행은 벡터 비활성화로 평가가 중단됐다. 모델을 직접 호출하니1024차원 생성에 성공했다. 이후 동일 캐시를 명시한 .venv/bin/python의 진단 추적 실행과 추적 없는 최종 실행 모두 성공했다. 두 실패의 정확한 원인은 이 증거만으로 확정하지 않는다. 실패한 실행을 품질 수치에 포함하지 않았으며 추적 실행 지연을 성능으로 보고하지 않는다.

재현 환경: TMPDIR=/var/tmp HF_HOME=/var/tmp/sb-bge-evaluation-hf HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 .venv/bin/python scripts/korean-search-acceptance.py --dataset tests/fixtures/korean_stale_decisions_v1.json --hybrid.

다음은 소비자에서 요구한 사실의 근거 존재와 검증된 최신 상태를 함께 검사하는 기존 경로를 대조하는 것이다. 작은 합성 진단으로 사용자 기반100–300개 평가를 대체하지 않는다. 제품 코드/운영 설정/모델 다운로드/타 리포 변경 없음. 공통 기억 운영과 전체 M1–M14는 미완료다.
