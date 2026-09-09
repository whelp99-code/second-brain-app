# Scoped 검색: 독립 작성자 동시 실행 및 1,000페이지 측정

직전 제품 커밋9d32302의 요청 단위 무결성 검증을 대상으로 했다. 이번에는 제품 로직을 변경하지 않았다.

## 실제 독립 프로세스 검증

`tests/integration/test_scoped_search_concurrency.py`는 실제 봉인 세대에10개 기억(허용1/불허9)을 만든다. 별도 spawn 프로세스가 허용 기억100을 추가하는 successor를 준비하고 파이프로 준비 경계를 알린다. 부모는 generation pin을 얻고 writer의 진행을 허용한 뒤 검색한다. writer는 pin 해제 전 세대를 전환할 수 없다.

- pin 안에서 초기 검색 결과와 완전히 같은1건, 불허 질의0건, active generation 불변 및 원래 세대 디렉터리 존재를 확인했다.
- pin 해제 후 자식이 정상 종료하고, 새 pin은 다른 generation의2건(기존 결과 보존+추가 기억)을 반환했다.
- 새 세대에서도 불허 질의0건이며 이전 세대 디렉터리는 정상 처분됐다.
- sleeps 없이 파이프와 실제 잠금 수명으로 겹침을 구성했다. 합성 source scope·시각을 쓰는 provider library 시험이며 실제 MCP/native/운영 동시 갱신 인수로 확대하지 않는다.

관련 검사 `TMPDIR=/var/tmp uv run pytest -q tests/integration/test_scoped_search_concurrency.py tests/test_scoped_search.py tests/test_memory_access.py`: **15 passed / 9.82초**. Ruff 전체 및 diff 검사 통과. 직전 제품 전체1712/2skip과 이번 추가 검사를 구분하며 전체 검사를 반복하지 않았다.

## 용량 측정과 다음 개선 근거

동일 스크립트 `scripts/scoped-search-scale.py --pages 1000`을 실제 생성·봉인된 합성 세대에 실행했다. ScaleProbe 질의5.2513초/허용1건, forbidden 질의5.2034초/0건, 프로세스 peak RSS58,088 KiB(생성 포함), exit0. [원시 결과](SCOPED-SEARCH-CONCURRENCY-2026-09-10.json).

동시성 검사가 종료한 뒤 독립적으로 실행한 단일 측정이다. p95·운영 성능 보장은 아니다. 300페이지1.4초에서1,000페이지5.2초로 늘어 실제 대규모 사용을 위한 추가 개선이 필요하다.

같은 세대를 별도로 profile한 단일 질의는 약9초였으며 프로파일러 비용이 포함되므로 위 지연과 혼합하지 않는다. `iter_lexical_hits` 누적6.049초, frontmatter 해석3,000회/누적3.499초, subprocess.run2,000회/누적3.581초를 관측했다. 누적 시간은 서로 포함되므로 합산하지 않는다. 다음 개선은 후보 읽기에서 반복되는 Git 실행과 YAML 메타데이터 해석을 줄이는 것이다. 접근 검사 전 후보를 잘라서 비용을 숨기지 않는다.

M11 동시 실행의 provider library 근거는 강화됐지만, 실제 MCP/클라이언트·다중 정정/삭제 경합·운영 및 전체 M1–M14 인수는 남는다.
