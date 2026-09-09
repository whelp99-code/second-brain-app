# 실제 HTTPS provider 검증과 수락·실행 연결

## 구현

새 sb.scoped_provider_https.create_scoped_provider_https(config_path)는 서버가 지정한 비공개 파일에서 HTTPS origin·cookie_id·csrf_token·선택적 ca_file을 읽는 단발 Python 프로세스를 구성한다. 이전 bounded process의 전용 파이프·입력32KiB/출력4KiB·최대20초·프로세스 그룹 정리를 재사용하므로 DNS/TLS/응답 읽기도 전체 실행 한도에 포함된다.

설정 파일은 절대 경로, 현재 사용자 소유 일반 파일, 그룹/기타 사용자 접근 권한 없음, symlink 최종 항목 거절, 최대8KiB canonical JSON 조건을 적용한다. 매 호출 다시 읽어 자격증명 교체를 반영하며 내용과 HTTP 오류 본문을 출력하지 않는다. origin은 HTTPS만 허용하고 request body에서 URL/명령/자격증명을 선택하지 않는다. TLS 인증서/호스트 검사를 끄지 않으며 리디렉션과 압축/청크 응답을 수용하지 않는다. 200 응답에 정확한 Content-Length/JSON Content-Type과 bounded canonical JSON을 요구한다.

새 연결부를 기존 create_scoped_provider_authority에 전달하고 accept_scoped_request 및 RequestExecutor의 동일 콜백으로 연결했다. 정상 이외 HTTP 상태는 권한을 부여하지 않는다. 자비스는 응답 키를 canonical 순서로 직렬화하도록 조정했으며 commit b8bcea3이다. endpoint의 필드·검증 규칙은 유지한다.

## 실제 검증 결과

- Python 관련76개 통과(14.14초): HTTPS 실제 child/TLS 인증서 불신 거절/리디렉션 미추적/응답 초과·중복 JSON·HTML 거절/공개 권한·symlink·HTTP·헤더 삽입 설정 거절 및 기존 프로세스·판정·수락·실행 회귀.
- 전체 Ruff, 새 HTTPS 모듈 basedpyright 오류0/경고0.
- JARVIS gateway HTTP 회귀1개 통과(3.99초), 격리 TypeScript emit 및 변경 ESLint 통과.
- [실제 TLS·게이트웨이·별도 Python 프로세스 결과](SCOPED-PROVIDER-HTTPS-2026-09-09.json).

| 시나리오 | 실제 결과 | HTTPS 검증 호출 |
|---|---|---|
| 정상 | accepted → proved, 활성 세대 생성 |5|
| 수락 중 현재 policy 철회 | denied, 수락 원장 행 없음 |2|
| 실행 전 현재 policy 철회 | accepted → failed, 활성 세대/proof 없음 |3|
| 실행 전 원래 로그인 만료 | accepted → failed, 활성 세대/proof 없음 |3|

네 경우 모두 원래 dispatch attempt1/FK 오류0. 수락된 결과는 원래 자비스 attempt에 기록한다. 첫 실행은 읽기 전용 테스트 세대 디렉터리의 정리에 실패했으므로 성공으로 계산하지 않았다. 테스트 소유 root에 기존 정리 방식을 적용하고 네 경우 전체를 재실행해 exit0까지 확인했다. 실패 실행이 남긴 해당 임시 root도 정리했다.

이번 전체 pytest는 실행하지 않았다. 이전 전체1,275통과 수치를 현재 변경의 전체 검증으로 재사용하지 않는다.

## 운영 연결과 보류

실제 TLS 라이브러리와 gateway 로그인 발행/쿠키/CSRF·현재 세션을 거쳤다. 신뢰된 Tailscale 전달자는 fixture proxy이며 임시 인증서/CA·호스트/포트·시각·policy/dispatch를 사용했다. 실제 운영 Tailnet이나 사용자 계정에서 인수한 결과는 아니다.

정적 세션 판정 JSON을 인증 근거로 사용하는 구성은 계속 보류한다. 쿠키/CSRF 파일은 bearer 자격증명을 저장할 뿐이며, gateway의 현재 세션·정책 검사를 우회하지 않는다. 운영 자격증명 공급/회전과 provider 실행 설정, 공개 MCP scoped 쓰기 계약, 실제 에이전트 A 저장→B 새 세션 회수는 남는다. 인증서 검사 해제나 전달자 신원 헤더를 SB가 임의 생성하는 방식은 제공하지 않는다.

첫 활성 세대 이전 상태 조회, 원문/spool/로그/백업 삭제·복원/재유입 억제, 클라이언트별 수집/주입, 한글 검색 평가, GUI·운영 복구를 포함한 전체 M1–M14 목표는 유지한다. 운영 DB/서비스/vault/설정과 기존 migration은 변경하지 않았고 push/배포하지 않았다.
