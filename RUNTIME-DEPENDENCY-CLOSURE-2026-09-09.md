# 런타임 의존성 전체 대조 — 2026-09-09

대상: /var/tmp/jarvis-contained-candidate-k54z40zc/source (JARVIS e6984ad).

npm ls --omit=dev --all --json: exit0, problems 없음. 중복 참조 포함300개 dependency occurrence를 확인했다. npm ls --omit=dev --all --parseable도 exit0. 루트 제외 실제 설치 경로161개의 package.json version을 해당 package-lock.json packages 경로의 version과 모두 대조해 일치했다. 모든 경로는 후보 내부로 resolve된다. 직접 의존성7개 검사보다 범위를 넓혀 현재 플랫폼에 설치된 runtime 하위 의존성을 검증했다.

실행 결과와161개 경로/패키지/버전은 동명 JSON에 보존했다. 원시 npm 출력은 /var/tmp/contained-runtime-dependencies.json, /var/tmp/contained-runtime-paths.txt다. 네트워크 조회·패키지 설치·npm audit는 수행하지 않았다. 다른 OS용 optional package 설치를 요구한 검사나 registry tarball 무결성/취약점 검사도 아니다. 기존 파일 해시 인벤토리 및 실제 native SQLite·양쪽 설치본 연동 검증과 함께 평가한다.

운영 서비스/current/DB 변경 없음. 로그인 세션의 구버전 DB 보유, 불완전 프로세스 관측, 롤백·운영 설정 및 전체 M1–M14 인수는 아직 남는다.
