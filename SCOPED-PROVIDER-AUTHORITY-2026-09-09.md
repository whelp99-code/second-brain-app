# 현재 전송 권한과 provider 수락·실행 연결

인계 정본: [자비스 OSS 인계서](../Orca-JARVIS/docs/second-brain-oss-absorption-handoff-2026-09-07.md). 기존 SB `7632e48`, JARVIS `f733609`까지의 구현을 유지하고 이어서 검증했다. 이번 변경은 JARVIS의 전송 후 현재 권한 검사와 SB의 독립 프로세스 인수 도구다. SB 제품 수락·실행 코드는 변경하지 않았다.

JARVIS 구현 커밋: `197b649`.

## 판정

**내부 연동에서 실제 현재 권한 검사→수락→실행→저장 증명 생성은 동작한다. 운영용 공통 기억 전체 완성은 아니다.** 별도 Node 프로세스가 실제 임시 JARVIS DB·정책 파일·기존 서명 검토를 검사한다. Python은 그 결과의 요청/provider/scope/fence와 유효 시간을 대조한다. 인증 세션·시계·키는 fixture이며 공개 v4 쓰기 전송은 연결하지 않았다.

## 발견한 연결 결손과 수정

등록된 요청 reader는 queued/claimed만 허용한다. 전송 시도를 기록하면 dispatching, 후보는 accepted_unsettled가 되므로 등록 단계 검사를 provider callback에 그대로 연결할 수 없었다. 기존 fixture의 무조건 True callback은 실권한 연결의 증거가 아니었다.

- `memory-scoped-dispatch-binding.ts`: 기존 outbox·scoped binding·원래 attempt를 정확한 request digest/fence/invocation으로 결합한다. 전송 전 요청, 다른 fence, 만료된 요청을 거절한다. 새 claim·승인 소비·재전송을 만들지 않는다.
- `second-brain-write-authority.ts`, `memory-outbox-authority.ts`: 명시적인 전송 후 경로에만 후보의 해당 상태를 허용한다. 기존 원본 검증·분류 무결성·승인/철회 검사는 유지한다.
- `memory-scoped-outbox-reader.ts`: 원래 전송 시도에 대해 private spool과 현재 정책·소비된 범위 검토를 다시 읽는다. 기존 등록 reader는 전송 후 요청을 계속 거절한다.
- `memory-scoped-provider-authority.ts`: 외부 요청을 원장에 저장된 정확한 요청과 대조하고 현재 검사 결과를 반환한다. 유효 시간 경과, 시계 역행, resolver의 시계 인자 변조를 거절한다. 요청 본문에 적힌 agent/session을 인증 증거로 쓰면 안 된다.

accepted_unsettled는 이 경로에서 **전송 시도 시점의 기존 후보 상태**다. provider 수락이나 저장 완료를 뜻하지 않는다. reconciling에서도 원래 시도의 현재 권한은 확인할 수 있지만, 새 전송 권한은 생기지 않는다.

## 이번 검증

| 검증 | 결과 |
|---|---|
| 전송 후 권한·등록 reader·worker | 32 passed, 3 files, 25.79초 |
| 기존 authority/saga·scoped 등록/수락 소비 회귀 | 20 passed, 4 files, 16.89초 |
| Python 수락·실행·walking skeleton | 21 passed, 9.38초 |
| TypeScript 격리 emit, 변경 파일 ESLint | exit 0 |
| SB 전체 `ruff check sb tests` | 통과 |
| 실제 프로세스 정상 경로 | 현재 권한 검사 5회, provider proved, 활성 세대 존재 |
| 수락의 두 번째 검사 직전 정책 철회 | 검사 2회, 수락 거절, accepted 원장 행 없음 |
| 수락 후 실행 전 정책 철회 | 검사 3회, failed, 활성 세대 없음, proof 없음 |
| 각 시나리오의 JARVIS | attempt 1개, FK 오류 0, 자동 settled 없음 |

원시 결과: [독립 프로세스 결과](SCOPED-PROVIDER-AUTHORITY-2026-09-09.json). 정상·실행 전 철회에서는 실제 SB 수락 응답도 별도 Node 프로세스로 JARVIS 원장에 기록한다. Python 3개, 권한 검사 Node 10개, 수락 기록 Node 2개를 사용한다. 수락 도중 철회는 발행된 pending 파일이 남을 수 있으며, 파일이 전혀 없다는 주장이 아니다.

초기 인수 실행은 JARVIS fixture의 상대 config 경로 때문에 SB cwd에서 ENOENT로 중단됐다. JARVIS cwd에서 재실행해 세 시나리오를 통과했다. 테스트 초기의 revocation 열 이름과 readonly fixture 수정 오류는 시험 코드에서 수정했다. 제품 전체 테스트 수치는 이번에 재실행하지 않았으며, 이전 SB 전체 1,241 passed/2 skipped는 [이전 검증](SCOPED-READ-V3-ACCESS-2026-09-09.md)의 결과다.

재현: JARVIS에서 운영 dist 대신 격리 outDir로 TypeScript를 emit한 후 다음을 실행한다. 격리 build의 package/migrations 의존 준비는 기존 인수 도구와 같다.

```bash
TMPDIR=/var/tmp node /home/jm/orca/projects/second-brain-app/scripts/scoped-provider-authority-acceptance.mjs /absolute/path/to/isolated-jarvis-build
```

## 인계에 병합한 수정·개선·고도화 목록

아래는 구현 순서이며 완료 선언이 아니다. 기존 M1–M14 전체 범위를 축소하지 않는다.

| 우선순위·구분 | 기존 구현과 이번 진전 | 다음 구현 및 완료 증거 |
|---|---|---|
| P0 수정: 현재 권한 연결 | 이번에 실제 DB/정책 검사와 Python callback 조합 확인 | 운영 인증 세션과 요청에 결합한 전송 어댑터. 클라이언트 주장값으로 권한을 만들지 않고 사용 시 유효 시간·철회를 재검사 |
| P0 개선: 공개 쓰기 계약 | 내부 v4 수락/실행, J 등록·단일 attempt·수락 기록 존재 | 명시적 새 프로필의 쓰기·상태·영수증 계약과 배포 패키지, 구버전 worker 혼재 거절 검증 |
| P0 개선: 최종 완료 | proof 일관성 대조와 현재 artifact의 내용/분류 대조 존재 | 신뢰 가능한 provider 완료 영수증을 재시작 후 조회하고 원래 시도와 연결해 J 완료를 원자적으로 기록. 현재 세대가 바뀌어도 유효한 과거 완료를 오판하지 않음 |
| P0 검증: 공통 기억 사용 | 기존 MCP의 독립 읽기·재시작·scope 차단 검증 재사용 | 실제 서로 다른 agent가 A 저장→B 새 세션 회수. 원작업/candidate/request/record와 프로젝트·원문·버전을 한 줄기로 추적 |
| P0 수정: 범위 전 경로 | generation identity에 분류 결합, 승인된 페이지 분류 반환 완료 | 정책 rollback·전역 철회·hybrid·export·restore를 같은 범위로 검사. 옛 미결합 세대 전환 검증 |
| P0 개선: 삭제와 복구 | 기존 tombstone·재유입 억제·중단 복구 재사용 | native 세션/compaction/로그/WAL/백업까지 정정·삭제·복원 시나리오, 다중 작성자·혼합 버전 인수 |
| P1 개선: 에이전트 지원표 | 공통 MCP와 작은 context pack 재사용 | 실제 버전별 조회/쓰기/자동 수집/주입을 각각 측정. MCP 호환만으로 네 항목을 모두 지원한다고 표시하지 않음 |
| P1 고도화: 검색과 주입 | lexical/hybrid·근거·문맥 예산 재사용 | 한국어 실제 질문 100~300개에서 근거 회수, no_data, 낡은 사실, p50/p95, 주입량/비용 기준선과 개선 비교 |
| P1 개선: 운영 가시성 | 기존 처리 원장·화면/API 재사용 | 요청별 대기/실패/완료, 출처와 검색 준비 상태 표시. 복구 훈련에서 실제 RPO/RTO 측정 |
| P2 고도화: 관계 확장 | LightRAG 아이디어 후보 유지 | 위 검색 평가에서 필요한 경우만 작은 관계 확장 적용. 품질 이득과 삭제 일관성을 함께 검증 |

네 OSS의 역할은 인계서의 고정 커밋 조사에 근거한 **아이디어 흡수 후보**다. 이번에 upstream을 새로 조사하거나 코드를 복사하지 않았다. Tencent의 공통 범위는 현재 권한·공유 계약에, code-brain의 작은 문맥은 주입 예산에, memory-bank의 원문 계보·중복 방지는 수집/주입 수명에, LightRAG의 근거 검색·파생 결과 일관성은 평가/삭제에 대응시킨다. 네 서버 설치·전체 교체·일괄 Proxy 도입은 하지 않는다. dev-wiki/Git의 개발 결정 정본 역할을 유지한다.

## 운영 연결의 남은 경계

현재 검사 결과는 서명 토큰이나 재사용 가능한 grant가 아니다. 호출자가 받은 뒤 권한이 바뀔 수 있어 프로세스 간 원자적 권한 보장을 주장하지 않는다. 실제 adapter는 서버 소유의 인증 문맥과 요청을 결합하고 사용 시점에 유효성을 검사해야 한다. 이번 작업은 운영 DB·서비스·인증 설정·vault를 바꾸지 않았고 현재 운영 건강 상태를 측정하지 않았다.
