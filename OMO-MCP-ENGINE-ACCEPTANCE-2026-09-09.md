# 설치된 OMO MCP 엔진의 공통 기억 연결 — 2026-09-09

## 실제 설치 구성 대조

로컬 omo는 balance router를 거쳐 omo-ai 5.0.0-0.beta.46 / senpi 2026.9.7을 실행한다. 라우터의 --help 분기가 모델 probe 없이 전달하는 것을 코드로 확인한 뒤 실제 도움말을 조회했다. gjc는 SSH를 통해 다른 호스트의 실행물을 호출하는 wrapper였다. 원격 GJC는 실행하지 않았으며 로컬 프로그램으로 지원 여부를 추정하지 않았다.

## 구현과 검사

기존 phone-memory-client acceptance에 선택적 `SB_OMO_MCP_ENGINE=ABS_CONNECTION_JS`를 추가했다. 설치된 OMO의 ServerConnection을 직접 사용해 JARVIS phone-memory-client MCP 서버 프로세스를 시작하고 initialize/listTools/callTool/dispose를 수행한다. 사용자 설정을 변경하거나 전역 MCP 서버를 등록하지 않는다. 검사 로그는 메모리에만 처리하며 실제 자격증명은 기존 임시 fixture를 사용한다.

실제 HTTPS/MCP 쓰기→provider proved→자비스 settled/completed→새 agent 로그인→읽기 흐름에서, OMO 엔진으로 jarvis_memory_context 1회 호출하여 기대한 2개 기록을 확인했다. 기존 독립 SDK client 2개와 합쳐 HTTPS context 호출 3회. 정상/접수 중 철회/실행 전 철회/실행 전 만료 4경로 전체 exit 0. reader 철회 후 403과 FK 오류 0도 기존 통합 검사에서 유지됐다. Node 문법 검사 통과.

초기 실행은 자비스 fixture 설정을 읽는 cwd가 잘못되어 실패했다. 후보 루트로 수정한 뒤에는 raw 엔진 config의 enabled 값이 없어 disabled로 거부됐다. 명시적으로 enabled=true를 전달한 후 전체 검사를 재실행해 통과했다. 설치된 엔진 파일 digest와 정확한 결과는 동명 JSON에 남긴다.

## 지원 범위

이 결과는 설치된 OMO의 **MCP 연결 계층** 호환성이다. 실제 OMO 대화 세션에서 모델이 기억 도구를 선택했거나, 자동으로 대화를 수집/주입했다는 증거는 아니다. native 모델 호출은 0회다. 자비스는 신규 잠금 의존성 후보, provider는 현재 개발 구현, 신원 전달·정책·시각·내용은 fixture다. GJC 원격 연결, 다른 모델 간 A→B, 운영 계정 연결과 전체 M1–M14는 계속 미완료다.
