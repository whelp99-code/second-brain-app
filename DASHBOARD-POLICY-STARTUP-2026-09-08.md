# JARVIS 정책 로딩 수정과 공통 기억 완성 후속 목록

JARVIS `4d8bdf0`, SB 인수 도구 `aa7e76f`. 자비스 인계의 최종 방향을 유지하며 기존 기억 화면
인수에서 발견한 실제 시작·요청 처리 결함을 수정했다. 세컨드브레인은 기억 정본, 자비스는
실행·검증, dev-wiki는 개발 결정 정본이다. 네 OSS의 장점을 선별 흡수하며 별도 제품을 설치하지 않는다.

## 이번 수정과 검증

| 문제 | 수정 | 완료 증거 |
|---|---|---|
| 실행 cwd에 config가 없으면 요청 중 ENOENT로 프로세스 종료 | source/compiled 모듈 기준 고정 경로 사용 | 잘못된 cwd 정책이 있는 다른 디렉터리에서도 실제 HTTP 200 |
| 요청마다 remote approval 서비스 생성 | 서버 시작 시 한 번 구성 | spy 1회 및 시작 후 정책 변경에도 요청 정상 |
| backend 배포 자산에 정책 파일 누락 | 기존 src 출력에 복사, artifact hash·원자적 게시 범위 포함 | 정규 격리 build manifest·정본 byte 일치 |
| 명시적 정책 설정과 오류 처리 부족 | 호스트 절대 경로 옵션, CLI --policy 한번 resolve, 정규화된 시작 오류 | 누락·잘못된 정책 listen 전 거부, CLI 주소 출력 없이 exit 2 |
| CLI 정책 구성 실패 시 DB 미정리 | memory transport 준비 전 검증, 실패 시 DB close | close 호출 회귀 검증 |

정책은 일반 파일·256KiB 상한·최종 경로 symlink 거부·읽기 전후 metadata 비교를 적용한다.
metadata 비교는 최선 노력 탐지이며 동시 writer에 대한 원자적 snapshot 보장이 아니다.
O_NOFOLLOW는 부모 디렉터리 symlink까지 차단하지 않는다. 정책/환경 변경 반영에는 재시작이 필요하다.
CLI의 모든 종류의 시작 실패에 대한 자원 정리를 완성했다고 주장하지 않는다.

수정 전 3개 실패를 재현했다. 수정 후 관련 4파일 14개, build 게시 10개가 통과했다.
backend TypeScript·변경 ESLint·Node syntax·diff 검사와 독립 검토를 완료했다.
copy 스크립트의 기존 process 전역 린트 오류는 명시적 import로 수정했고 정규 build와 실제 인수를 재실행했다.
이번에는 backend 전체 회귀·dashboard 전체 UI·SB 전체 Python 테스트를 반복하지 않았다.

실제 인수는 새 격리 build와 독립 Node 프로세스 6개를 사용했다. 기본 서버/명시적 고정 정책 서버,
누락/오류 정책 서버 시작, 정상 CLI, 누락 정책 CLI를 확인했다. 정상 서버의 health·memory status는
200, 정상 CLI는 SIGTERM 후 exit 0이었다. memory status 200은 실제 기억 검색·운영 준비의 증거가 아니다.
원격 승인은 기존 signer 미준비 경계를 유지한다. 운영 DB·실제 모델·서비스 배포·push는 사용/수행하지 않았다.

[기계 증거](DASHBOARD-POLICY-STARTUP-2026-09-08.json). 최종 fixture는
`/var/tmp/jarvis-policy-acceptance-YA3b5x`, build는 `/var/tmp/jarvis-policy-build-1qaj70f8`이다.
검증 서버와 CLI는 종료했다. fixture에는 합성 DB/정책이 남는다.
재현: 소스 사본에서 `TMPDIR=/var/tmp node scripts/build-backend.mjs`로 dist를 만든 뒤 SB 작업공간에서
`TMPDIR=/var/tmp node scripts/jarvis-policy-startup-acceptance.mjs /absolute/isolated/source-root`.

## 수정·개선·고도화의 남은 우선순위

기존 전체 목록을 대체하지 않는 현재 실행 순서다. 이전 실제 Codex↔Claude 공유와 정정·삭제 검증을
재사용한다. 이번 HTTP 확인을 여러 에이전트의 자동 수집·주입 완료로 확대하지 않는다.

| 우선순위/구분 | 남은 문제와 필요한 작업 | 완료 판정 |
|---|---|---|
| P0 수정 | native rollout·thread_history SQLite/WAL·백업의 원문 잔류: 관리형 소유권과 writer 중단·세션 폐기 연결 | 실제 앱의 삭제/정정 후 관련 보존 표면 검사와 오래된 복원 거부 |
| P0 수정 | DB 전송 claim과 외부 수신 사이 삭제 경합 | 실제 소비자 수신 fence·늦은 확인·강제 종료 시 미확정 재전송 차단 |
| P0 개선 | 검증된 사용자·프로젝트 ACL과 원본 분류 | 검색·상세·관계 확장·쓰기·내보내기·복원 전 경로의 비허용 범위 차단 |
| P0 개선 | JARVIS 실제 작업의 기억 공급과 검증 결과 저장 연결 | 조회→승인된 입력 결합→작업 검증→저장 영수증→다음 요청 회수 |
| P0 수정 | 실패/미확정 실행의 성공 기억 승격 가능 경로와 원본 차단 계보 | 실패 증거를 성공으로 저장하지 않고 정정·차단이 파생 결과에 전파 |
| P1 개선 | 실제 native session/compaction 이력 연결 | 실제 epoch 변화에 따른 중복·예산·오래된 문맥 차단과 영수증 대조 |
| P1 개선 | 의미 유사 후보와 답변 근거 충분성 구분 | 답 없는 질문 no_data, 최신 출처 회수 평가; 유사도 점수만으로 성공 판정 금지 |
| P1 개선 | 검색 지연과 모델 메모리 | 고정 평가 세트의 p95·메모리 측정 후 기존 배치/검색 개선 효과 비교 |
| P1 개선 | 실제 질문 100~300개 및 앱별 지원표 | 실제 질문의 근거 정답과 client별 읽기/쓰기/수집/주입 개별 실측 |
| P1 수정/운영 | 화면 전역 연결 배지 끊김과 준비 상태·복구 인수 | 실제 연결 상태의 일치, 운영 백업 복구·RPO/RTO 측정 |
| P2 고도화 | 전역 무효화의 비용과 관계 검색 필요성 | record 계보별 선택 무효화 정확성·성능, 관계 확장은 기준선 개선이 입증될 때 도입 |

native 자동 주입은 관리형 보존·실제 수신 경계가 연결되기 전까지 보류한다. 기존 task provider는
승인된 execution-plan digest와 source snapshot에 입력이 결합되므로 기억을 임의로 덧붙이지 않는다.
운영 hybrid 검색도 근거 충분성/지연 검증 전까지 보류한다. 새 그래프 DB·Proxy·에이전트별 기억 DB는
현재 근거가 없어 도입하지 않는다. 중앙 기억의 전체 구현·운영 인수는 계속 미완료다.
