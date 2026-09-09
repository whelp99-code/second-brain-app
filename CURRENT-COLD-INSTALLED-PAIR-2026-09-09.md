# 최신 설치본 첫 실행 인수 — 2026-09-09

제품 SB 5fcc28c / JARVIS e6984ad의 새 설치본을 검증했다. SB는 웹 실패 표시·상태 세대 고정·CLI 설정 경로·원본 진단 경로 수정까지 포함한다.

최종 provider: `/var/tmp/sb-full-bytecode-candidate-rkr0pdms/releases/56eb7ba2b39b3ae73b4d5ab46d3b80d5d23ccbe0`

JARVIS: `/var/tmp/jarvis-contained-candidate-k54z40zc/source/dist`

첫 검증에서 후보 내용 변경으로 거부됐다. MCP 초기화와 연동 검사를 함께 실행한 것이 원인이라는 초기 가설은 충분하지 않았다. 초기화를 순차 실행하고 캐시 생성을 억제해도 새 provider의 첫 연동에서 실패했다. 별도 새 후보의 전후 전체 목록을 직접 대조해 변경548개가 전부 pyc 또는 __pycache__ 항목임을 확인했다. 자비스의 제한된 환경 전달 경로는 상위 PYTHONDONTWRITEBYTECODE를 그대로 전달하지 않는다.

변경:

- prepare-release.py의 의존성 설치와 앱 설치 **양쪽**에 uv --compile-bytecode를 적용했다. 앱 설치에만 적용한 중간 시도는 의존성 첫 실행 쓰기가 남아 실패했다.
- check-release-mcp.py도 실행 환경에 PYTHONDONTWRITEBYTECODE=1을 전달한다.
- bytecode를 inventory에서 제외하지 않았고 변경 검사도 완화하지 않았다.

최종 검증은 새 후보에서 warmup 없이 시작했다. 전체 inventory 기록 → 실제 설치 MCP 4프로파일 초기화 → inventory 일치 → 실제 TLS/gateway/CLI/MCP 정상·수락 중 철회·실행 전 철회·만료 4경로 → 전후 전체 inventory 일치. **exit0, 변경0**. 정상 저장 proved/settled/completed 및 독립2클라이언트 각각2기록 재조회, 철회403/FK0. [원시 결과](CURRENT-COLD-INSTALLED-PAIR-2026-09-09.json).

실패한 중간 후보는 최종 인수 성공으로 집계하지 않는다. 한 번 실행해 캐시가 생긴 후보의 재실행 통과만으로도 결론내리지 않았다. 관련 배포 검사16개 통과. 운영 DB/current/서비스 변경, native 모델 호출, 실제 사용자 업무 인수는 수행하지 않았다. 이 후보는 검증한 설치 결과이며 영구 쓰기 방지 봉인·운영 전환 승인과는 별개다.
