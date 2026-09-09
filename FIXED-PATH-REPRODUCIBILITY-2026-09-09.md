# 고정 설치 경로 재현성 — 2026-09-09

서로 다른 경로의 기존 비교는5,395항목 차이가 났다. 설치 경로가 실행 스크립트·Python code filename에 들어가므로 이번에는 **같은 최종 경로**에서 같은 입력을 두 번 준비해 비교했다. 첫 결과는 완전히 종료한 뒤 별도 디렉터리로 보존하고, 같은 원래 경로에 두 번째 결과를 생성했다. 운영 경로는 사용하지 않았다.

준비 도구 변경:

- 앱 wheel을 임시 build 디렉터리가 아닌 release 내부 고정 위치에서 설치하고 wheel mtime을 원본 커밋 시각으로 고정한다.
- 최종 경로에서 PYTHONHASHSEED=0과 checked-hash 모드로 bytecode를 강제 재생성해 설치 시각 차이를 없앤다.
- uv 앱 설치의 uv_cache.json 시간 정보·RECORD 차이가 끝까지 남아, 앱 wheel만 번들 pip로 --isolated/--no-index/--no-deps/--no-compile 설치한다. 잠금 의존성 설치는 기존 uv를 유지한다. 설치 metadata를 임의 수정하거나 inventory 비교에서 제외하지 않았다.

실측:

1. 첫 개선 후 고정 경로 비교: uv_cache.json과 RECORD의2파일 차이로 재현성 미통과.
2. 최종 pip 경로 적용 후: **18,456항목 차이0**, 양쪽 전체 entries SHA256 일치. [원시 증거 및 builder 파일 해시](FIXED-PATH-REPRODUCIBILITY-2026-09-09.json).
3. 앱 RECORD의 실제 해시·크기182항목 검증 통과.
4. 두 번째 설치 후보의 실제 TLS/gateway/CLI/MCP4경로와 실행 전후 후보 동일성 검사 통과. JARVIS 후보는 e6984ad다.
5. 관련 배포 검사20개 통과/0.31초, diff check 통과.

후보: `/var/tmp/sb-repeat-pip-fixed-_remyuep/releases/18e9d889f90cc595533f1f5317b140e95cec9e14`.

**입증 범위는 동일 경로·동일 로컬 환경·고정 입력의 두 번 준비다.** 다른 설치 경로의 바이트 일치, 다른 호스트/도구 버전, source-only offline cache 재구축, artifact의 이동 가능성은 입증하지 않았다. preserved 첫 사본의 스크립트는 원래 경로를 참조하므로 이동한 위치에서 독립 실행 가능하다고 주장하지 않는다. 정본 manifest/영구 봉인·운영 전환·실제 사용자 및 에이전트 인수는 계속 남는다. 운영 current/DB/서비스 변경 없음.
