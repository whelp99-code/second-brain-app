# 최신 scoped 읽기 설치 인수

소스5f242ed876ff2e3a16dbe497b3273b903eac1339(제품8e5b4a3 및 변조 회귀 검사)을 git archive/offline locked 설치했다. 릴리스5b915cf48c8c8e05a39b80fd0c3c45c00e13d4e3, wheel SHA-256 ea6e58da326f01da15092e790da81183521b1ceff05cb71a78e49c098f143906.

설치 위치 `/var/tmp/sb-shared-read-release-_unp2axf/releases/5b915cf48c8c8e05a39b80fd0c3c45c00e13d4e3`. 기존 격리 자비스 빌드와 check-release-integration.py, 같은 설치물의 check-release-maintenance.py를 순차 실행해 둘 다 exit0을 확인했다.

- 실제 TLS/HTTP/CLI/MCP 공개 저장→provider proved→자비스 settled/control completed→새 로그인 회수2records, 독립stdio reader2개 각2records. settlement/attempt1, FK0, reader 철회403.
- 접수 중 철회는 accepted row 없이 거부, 실행 전 철회/만료는 failed·active generation 없음.
- 살아 있는 복원 workspace는 보존; worker SIGKILL(-9) 뒤 정리1, 재실행0. 새 프로세스3회에서 유지 기억1개·generation/body/ledger/high-water 동일.
- paired 실행 전후 provider18,474·자비스19,588개 inventory 및 Node 파일 불변. provider inventory SHA-256 df5e124e3a50f02e449ff1c5050a6fd2092fc5b02f821ddacbe6bc8f875f1df4.

[상세 JSON](INSTALLED-SHARED-READ-2026-09-10.json). 원본prepare/paired/maintenance 출력은 위 릴리스의 상위 app root에 있다. 검증은 합성 신원/업무/clock이며 native 호출0. 운영 current·서비스·DB는 변경하지 않았다. 최신 전체pytest1730통과는 이 제품 변경 이전 결과이므로 별도로 유지한다. 실제 사용자 업무·운영 및 M1–M14 전체 목표는 남는다.
