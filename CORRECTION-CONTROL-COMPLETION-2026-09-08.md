# 자비스 정정 완료 연결 — 구현·검증 및 잔여 분석

2026-09-08. 자비스 구현 커밋 `4721358`. 인계서의 Second Brain 유지·OSS 장점 선별 흡수·자비스와 공통 기억 우선 방향에 따른 I1-d/G4 후속이다. 기존 SB `ec2a758`의 여러 줄 정정 렌더링과 자비스의 V2 correction saga를 연결했다. 새 기억 DB나 OSS 서버를 추가하지 않았다.

## 판정과 범위

**격리된 실제 세컨드브레인에서 정정→자비스 완료→두 MCP 클라이언트의 같은 정정 기억 회수를 검증했다.** 최종 완료 이벤트 저장 실패 후 자비스 시계를 20분 진행해도 provider 재조회·재전송·추가 compaction 없이 복구됐다. 운영 릴리스 전환과 실제 앱의 자동 기억 수집·문맥 주입은 미완료다.

이 단위의 제품 수정은 자비스의 기존 lifecycle 경로에 있고, 세컨드브레인에는 실제 연동 하네스와 분석·진행 기록을 추가했다. SB의 frozen V1/schema4/V2 wire는 변경하지 않았다. 최초 회귀 기준은 자비스 `9762b53`, 마지막 호환 확인 기준은 다른 작업이 확정한 `60ee750`과 이번 소스다. 다른 작업의 미커밋 변경을 섞지 않은 `/var/tmp/jarvis-correction-control-yh2fnz4c`에서 빌드했다.

## 발견한 수정 항목

| 우선순위 | 문제와 영향 | 수정 및 완료 기준 |
|---|---|---|
| P1 | correction 원장의 settled와 control 완료가 별도 commit이었다. 사이에 종료하면 저장은 됐는데 명령은 claimed/uncertain으로 남았다. | 원장 settlement·control effect·완료 상태·event·preparation 갱신을 같은 immediate transaction으로 묶었다. event 실패 시 effect/완료 상태가 남지 않는지 검증했다. |
| P1 | settled 요청은 reconcile에서 바로 반환하고 주기 조회에서도 빠졌다. 과거 중단 상태가 회복되지 않았다. | settled와 불일치한 명령을 bounded cursor로 조회하고 저장된 증거로 완료 상태를 복구한다. claimed/uncertain 각각의 과거 gap을 검증했다. |
| P1 | compaction 뒤에도 앞서 읽은 now를 사용했다. 실제 완료 시각과 lease/승인 만료 판단이 어긋났다. | await 이후 clock을 다시 읽는다. compactor에도 같은 clock을 주입한다. 전송 시 유효했던 승인을 검증하되 새 실행 권한으로 사용하지 않는다. |
| P1 | compaction이 control target/args를 지우므로 원래 명령 digest를 재검증할 자료가 사라졌다. | 전송 전 schema3의 원문 없는 후보 ID/digest와 lane/provider/기한을 immutable binding으로 보존한다. 지워진 target/args는 다시 노출하지 않는다. |
| P1 | 이미 완료한 compaction을 재실행하다 pending/replay 오류에 걸렸다. provider 조회가 먼저여서 provider 중단·세대 변경 때도 복구가 막혔다. | provider_proved와 completed purge가 있으면 저장된 proof/receipt로 먼저 복구한다. offline observer를 호출하지 않는 회귀를 추가했다. |
| P2 | 복구 cursor 저장 실패가 이미 완료한 건수와 나머지 lifecycle 실행에 영향을 줄 수 있었다. | 복구 배치와 cursor를 같은 transaction으로 묶는다. cursor 실패는 rollback 후 완료 0건과 명시적 오류로 반환한다. |

## 복구 증거와 경계

복구는 원 명령 digest, owner의 서명 receipt, 원 control fence의 redemption 및 전송 시각을 대조한다. 정정 preparation의 후보·provider·요청·대상·범위·payload·spool digest도 원장과 같아야 한다.

provider proof는 기존 strict 검증기로 JSON 형식·digest·release에 결합된 키·서명·요청·tombstone·결과 세대를 다시 확인한다. 검증 시각은 기록된 관측 시각을 사용하고 현재 키 폐기 상태도 반영한다. 정정 attempt와 이벤트의 hash·순서·시각, 같은 lane의 purge job·compaction receipt·완료 run·70개 surface의 집계 상태를 함께 대조한다. 이때 compaction receipt는 자비스 원장의 완료 증거이며 새 provider 서명을 만들지 않는다.

취소·철회된 명령은 완료로 승격하지 않는다. 다른 fence, 폐기된 provider key, 누락 binding, 변조한 proof signature·purge digest는 거부한다. 기존 settled 행의 control 내용이 이미 삭제됐고 binding도 없다면 추정 복구하지 않는다. 원문이 든 과거 DB나 백업에서 개인정보를 되살려 binding을 만드는 기능도 추가하지 않았다.

## 검증

- 새 회귀 11개: 승인/lease 만료, event 실패 rollback과 offline 복구, 과거 settled/claimed·settled/uncertain, cursor 실패 rollback, key/fence/cancel/revocation/binding/signature/purge 증거 손실.
- 관련 회귀 34개 / 9개 파일 통과, 50.15초. control plane·lifecycle executor·실제 AuthorityDb compaction·단일 destructive dispatch·preparation·provider proof·observation manifest를 포함한다.
- 후속 자비스 `60ee750`과 병합한 격리 소스에서 핵심 24개 / 4파일 통과, 42.49초. 위 34개와 중복이며 합산하지 않는다. 같은 기준의 실제 MCP 정정 인수도 통과했다.
- backend TypeScript build와 변경 파일 ESLint `--max-warnings=0` 통과. 독립 리뷰의 두 지적을 수정했고 재검토에서 새 blocker가 없었다.
- SB Python 제품 소스는 이번 단위에서 변경하지 않았다. 기존 `ec2a758`의 전체 571 passed / 2 skipped 기록을 이번 검사로 재계산하지 않는다. JARVIS 전체 `npm run verify`나 운영 smoke를 통과했다고 주장하지 않는다.

실제 연동 실행:

```bash
cd /home/jm/orca/projects/second-brain-app
TMPDIR=/var/tmp node scripts/jarvis-correction-acceptance.mjs /var/tmp/jarvis-correction-control-yh2fnz4c --control-cycle
```

| 관측 | 결과 |
|---|---|
| 후보 확인·dispatch | 기존 candidate/control API 및 합성 owner 서명 fixture |
| 정정 provider / 자비스 control | proved / completed |
| 최종 event 실패 후 재개 | 원래 control claimed 유지, 20분 뒤 완료 |
| 정정 전송 / 실제 DB compaction | 각 1회 |
| lifecycle 관측 호출 | pending 1회 + proved 1회; 복구 중 추가 0회 |
| 두 독립 MCP 클라이언트 | 모두 current, 같은 record ID 4개 |
| 정정 문장 | LF/CRLF·빈 줄·반복 문장·사용자 citation 문자의 내용 digest 일치 |
| 정정 전 기억 | 검색 record 0개 |
| 출처 | 모든 record가 해당 memory-effect 요청 출처에 결합 |
| 과거 read fence / 바꿔치기 payload | TOMBSTONE_SET_STALE / SECOND_BRAIN_TOOL_ERROR |
| 동일 wire replay | replayed=true, 추가 provider apply=idle |

다중 행의 cursor 공정성과 다른 lane의 정상 purge 영수증 교체는 별도 fixture로 시험하지 않았다. 이번 회귀는 단일 행 재개/실패와 변조 purge digest 거부를 검사했다.

20분 진행은 자비스 복구 clock이다. Python provider와 읽기 fixture는 고정된 원래 시험 시각을 사용한다. 서로 다른 MCP 프로세스의 계약 검증이며 실제 Claude/Codex/기타 앱의 세션 자동 주입을 검증한 것은 아니다. 합성 owner 승인은 실제 사용자의 승인 UI 인수를 대체하지 않는다.

실행 로그: `/var/tmp/jarvis-correction-control-regression.log`, `/var/tmp/jarvis-correction-control-current-head.log`, `/var/tmp/sb-jarvis-correction-control-current-head.log`. 임시 로그는 운영 보존 산출물이 아니며 재현 코드와 이 문서가 리포에 남는다.

## 수정·개선·고도화의 다음 항목

| 구분 / 우선순위 | 남은 일 | 완료 증거 |
|---|---|---|
| 수정 / P1 | V1 remember 일반 LF의 새 body version/profile 계약 | 기존 V1 fixture는 유지하면서 여러 줄 신규 저장→인용→서명→복원 성공 |
| 개선 / P1 | 정정 대상 선택·변경 내용 검토·owner 승인·완료 UI 연결 | 실제 화면에서 선택한 대상과 승인한 내용이 같은 요청으로 저장되고 새로고침 후 완료 유지 |
| 개선 / P1 | task 결과 수집의 원본 차단 전파 계약 — 현재 보류 | 수집 전/후·전송 중·저장/복원 후 task 차단이 파생 기억까지 적용 |
| 개선 / P1 | 실제 앱별 공통 기억 인수 | 앱 A 기록→앱 B 회수, 정정·삭제 반영; 연결·읽기·쓰기·수집·주입 능력별 판정 |
| 고도화 / P1 | project/user/agent 접근 범위 | 범위 밖 기억 노출 0건과 명시적 공유 정책; 기존 지식 상태 scope와 분리 |
| 고도화 / P1 | 작은 context pack·세션별 실제 전달 receipt | byte/token 예산, 중복 공급 억제, 변경·compaction 이후 필요한 기억 재공급 |
| 개선 / P1 | readiness·복원·운영 인수 | 검증된 백업 복원, 정체 요청·최근 실패 감지, 실제 release의 저장·조회·복구 |
| 고도화 / P2 | hybrid 결합과 한국어 품질·부하 | 필터/출처/세대/삭제 수명 일치, 고정 질문 평가와 p95; 증거 전 활성화 보류 |

LightRAG의 검색·근거, Tencent의 공통 인터페이스·범위, code-brain의 작은 문맥, memory-bank의 출처·정정·전달 중복 억제라는 인계 방향을 기존 R/I/G 항목에 유지한다. 이번에 외부 OSS 코드를 복사하거나 의존성을 추가하지 않았다. 운영 DB migration 적용·서비스 재시작·배포·push는 수행하지 않았다.
