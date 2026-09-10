# 봉인 scoped 검색 반복 지연 기준선

기존 scale 도구는 질의당 단일 실행만 기록했다. `--repetitions`(기본1, 범위1–100)를 추가하여 같은 세대에서 각 질의를 반복하며 검색 순서를 교대한다. 첫 조회를 버리지 않는다. 매회 허용1개/불허0개와 불허 본문 미노출을 검사하고 원시 표본, p50 median, p95 nearest-rank, 최소/최대 시간을 함께 남긴다.

제품4d7d0c4의 실제 합성 봉인1,000페이지(허용1, 불허999)를 각20회 검색했다. 생성/색인은 타이머 밖이며 해당 실행의 RSS에는 생성 비용이 포함된다. 명령: `TMPDIR=/var/tmp .venv/bin/python scripts/scoped-search-scale.py --pages 1000 --repetitions 20`.

| 질의 | 표본 | p50 | p95 | 최소–최대 | 매회 결과 |
|---|---:|---:|---:|---:|---|
| ScaleProbe | 20 | 2.1972초 | 2.2905초 | 2.1332–2.2959초 | 허용1개 |
| forbidden | 20 | 2.1777초 | 2.1982초 | 2.1342–2.2083초 | 0개 |

40회 assertions 모두 통과·exit0. peak RSS58,236KiB. [원시 결과](SCOPED-SEARCH-REPEATED-2026-09-10.json), 생성 저장소 `/var/tmp/sb-scoped-scale-0nvua0ht`. 원시 표본에서 median과 nearest-rank를 별도 계산해 요약 일치를 확인했다. 반복 인자0/101은exit2. Ruff/diff통과.

동일 프로세스·같은 세대·warm cache 영향을 포함한 소표본 library 측정이며 운영 MCP 왕복·모델·동시 정정·다중 사용자 p95가 아니다. 현재1,000페이지에서 약2초인 후보 처리 비용이 다음 최적화 기준이다. 그래프 도입이나 접근 검사를 줄이는 것으로 우회하지 않는다. 실제 사용자100–300 gold, 큰 corpus/MCP/동시 갱신 인수 및 M1–M14 전체 목표 유지. 제품코드·운영서비스 변경 없음.
