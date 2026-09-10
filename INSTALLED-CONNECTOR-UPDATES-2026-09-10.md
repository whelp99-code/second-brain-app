# 누적 커넥터 수정 후 설치물 자비스 인수

소스/fixture 커밋 `13cab776643574f6559282e26d93087694e55cf6`을 git archive에서 offline locked 설치했다. 릴리스 `0d6938efdf9073044c9cd0f63b8d6972e24c0793`, wheel SHA-256 `3c5c5ddeaab9979839575c379c91a5b0225c1d4d7dd6328b1b9fbf2b59b9db08`.

설치 위치 `/var/tmp/sb-connectors-release-o9xq0aek/releases/0d6938efdf9073044c9cd0f63b8d6972e24c0793`. 준비 시 작업공간에는 문서 편집 및 기존 미추적 파일이 있었으나, 커밋된 트리만 사용했다. 실행 중 제품 코드와 테스트를 수정하지 않았다.

`check-release-integration.py`에 기존 격리 JARVIS 빌드 `/var/tmp/jarvis-current-pair-_mq15nmd/source/dist`를 연결하여 exit 0. 같은 설치물의 `check-release-maintenance.py`도 순차 실행하여 exit 0.

- 실제 TLS/HTTP/CLI/MCP 공개 저장 → provider proved → JARVIS settled/control completed → 새 로그인 2개 record 회수.
- 독립 stdio reader 2개가 각각 2개 record 회수. 완료 재전송 후 settlement 1·attempt 1·FK 오류0. reader 철회403.
- 접수 도중 철회는 accepted row 없이 거부. 실행 전 철회/만료는 failed 및 active generation 없음.
- 살아 있는 복원 workspace는 보존. worker SIGKILL(-9) 후 폐기1·재실행0. 새 프로세스3회에서 유지 기억1개 및 generation/body/ledger/high-water 동일.
- paired 검사 전후 provider18,474항목·JARVIS19,588항목 전체 inventory와 Node 파일 불변. provider inventory SHA-256 `3ba9bf903a2c7bd507c417337c769a7c2c5662e70eab3e48ddd4d05b943d429e`.

원본을 합친 결과는 [JSON](INSTALLED-CONNECTOR-UPDATES-2026-09-10.json). prepare/paired/maintenance 개별 출력은 위 app root에 보존했다. 전체 pytest와 설치 준비/인수의 실행 시간이 일부 겹치므로 실행 시간은 단독 성능 벤치마크가 아니다.

이 인수는 합성 신원·업무·고정 clock을 사용했고 native 호출0이다. 운영 current·서비스·DB를 변경하지 않았다. 실제 사용자 업무, 각 native 제품의 자동 수집·문맥 주입·정정/삭제 전체 수명과 M1–M14 전체 인수는 남아 있다.

추가 설치 커넥터 인수: 같은 릴리스의 `.venv/bin/python -I -m sb.cli`로 별도 환경 `/var/tmp/sb-installed-opencode-sources-l0pw0487`에서 init+ingest3회를 실행했다. 같은 본문/항목 ID의 A/B 두 source가 원장에 별도 남고, A만 변경하면 A2개/B1개와 B 커서 불변, 재실행 원장·커서 불변을 확인했다. 합성 export이며 native 모델 호출 없음. 위 JSON의 installed_opencode에 원본 결과를 포함했다.
