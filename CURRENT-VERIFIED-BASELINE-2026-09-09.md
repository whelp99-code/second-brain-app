# 최신 제품·설치본 통합 검증 기준 — 2026-09-09

제품 커밋 **SB 997e81473145b63123d49457184b4d7050bf86a4 / JARVIS e6984ad**. 최근 웹 실패 표시·상태 세대 고정·설정 경로·복구 게시 실패 복귀·staging 소유권·대상 잠금까지 포함한다. 아래 검사는 코드 수정 없이 같은 기준에서 수행했다.

- 전체 pytest: **1,469 passed, 2 skipped / 273.49초**, embeddings 파일 제외. [전체 출력](CURRENT-VERIFIED-BASELINE-2026-09-09.txt). 실제 임베딩 품질의 새 종합 인수는 아니다.
- Ruff sb/tests 통과.
- git archive 고정 소스의 새 provider 설치본 + 기존 contained JARVIS 설치본에서 실제 TLS/gateway/CLI/MCP 4경로 통과. 정상 저장 proved/settled/completed 및 새 로그인 독립2클라이언트 각각2기록 회수, 철회·만료 차단.
- 설치 실행 파일의 read-v2/read-v5/status-v1/write-v1 MCP 초기화·목록 4개 통과.
- **설치된** sb.web을 별도 Python 프로세스에서 실행하고 import 경로가 release 내부인지 확인했다. 실제 Chromium으로 실패23/생략3/보류 안내/비밀값 가림/오류 HTML 비실행/통신 실패 후 상세 제거 확인, pageerror0. 합성 vault를 사용했다.
- 연동 전후 및 브라우저·MCP 검사 종료 후 provider inventory digest 일치. 실행기·후보 내용이 바뀐 상태의 결과로 기록하지 않았다.

[원시 검증 요약](CURRENT-VERIFIED-BASELINE-2026-09-09.json).

후속 작업 기준 후보:

`/var/tmp/sb-restore-verified-candidate-tq6jcs29/releases/16c2c6248a07c8abccd76725acb0a520d5b17b20`

JARVIS build:

`/var/tmp/jarvis-contained-candidate-k54z40zc/source/dist`

이 결과는 운영 배포나 전체 목표 완료가 아니다. 신원·시각·원작업은 fixture이며 native 모델은 호출하지 않았다. 영구 후보 봉인, 모든 구버전 작성자 정지와 DB 전환, 실제 계정·서로 다른 에이전트 인수, 관리형 세션 삭제 수명, 과거 실패 복구, 실제 한국어 검색 평가, 강제 종료 복구 및 RPO/RTO 등 기존 미완료 조건은 유지한다. 운영 current/DB/서비스 변경 없음.
