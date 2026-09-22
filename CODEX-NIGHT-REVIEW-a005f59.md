# 야간 독립 검토 — a005f59 미통과

작성자: 기존 Codex 감시 작업 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`, 야간 독립 검증 위임. 원래 Codex 직접 실행 아님. `2026-09-11T18:06:02.022831+00:00`. **제품 준비/운영 최종 인수 아님.**

## 고정 후보

제출 `a005f59f2c321dd9f919fb43aa1ff0630f7bee53`, SB source `8db46c59f249ff2da483336c0ec3318e2d317859`, release `0ecdb5617a1fe95697e55366f631ee4373f407b1`, wheel `0e32b787c97a42d922132e93e3c67ab375d06154b433d23a042283112cbf0b57`. 후보 `/var/tmp/sb-candidate-8db46c5/releases/0ecdb5617a1fe95697e55366f631ee4373f407b1`. SB archive/휠/설치물 Python182개 일치. 제품 sb 바이트는 f94d073 이후 동일하며 이번 변경은 script/test/문서다.

JARVIS `bcb47af`, dist `/var/tmp/jarvis-artifact-bcb47af/source/dist`, inventory `964aeaa543b30c7bde6e2dfb988586261801979fd6669490052990dc5994d632`/34780. 제품 tracked1137개 Git 소스 일치, 직접 tsc EXIT0, 재빌드 JS1109개와 제출 dist 바이트 일치. `sb-identity.json`, `jarvis-identity.json`, 설치 로그에서 확인했다.

증거/harness `/var/tmp/codex-night-a005f59-0nyj9qkh`. 합성 fixture만 사용했고 제품 소스/테스트/운영 상태는 수정하지 않았다. 검토 종료 HEAD는 고정 제출과 동일.

## N1: 회수 소유권과 만료 fencing (P1)

단일 child 중단 후 재시도는 sends1로 개선됐다 (`dispatch-crash.json`). 하지만 `gjc-intent-store.ts`의 prior 분기에서 새 worker용 `owner`를 `prior.lease_owner` 지역변수가 가린다. UPDATE는 **새 PID가 아닌 죽은 이전 PID**를 다시 쓴다.

`dispatch-reclaim-race.mjs`는 실제 child가 예약 후 전송 전에 exit99한 뒤 새 프로세스가 실제 DB를 열어 회수한다. 첫 재전송을 transport 경계에서 유지하고 두 번째 동일키 호출을 실행한다. 결과:

```text
old/dead PID 4188635, new PID 4188542
lease_after_takeover.owner=pid:4188635
sends=2; both ok=true, same intent_id
```

이는 순수 fixture이며 실제 Grok/운영 프로세스를 종료하지 않는다. 동기화는 promise rendezvous, sleep이나 내부 DB 소유권 수동 변경 없이 실제 public dispatch 경로다.

별도 `dispatch-live-expiry.mjs`는 child중단 없이 살아 있는 첫 worker의 전송을 유지한 채 두 번째 호출 시각만61초 전진한다. 60초 lease가 만료됐다는 이유로 첫 worker가 살아 있어도 두 번째 send가 시작되고 **sends2, 양쪽 oktrue**다. 토큰/소유권 fencing 없이 expiry만 추가해서는 겹치는 전송/늦은 결과를 제어하지 못한다. 운영에서 실제60초를 기다렸다고 주장하지 않는다; 시계는 의도적으로 제어한 fixture다.

완료 기준: 새 owner 기록, incarnation/lease 수명, 갱신/회수, 전송·원장 결과의 소유권을 하나의 계약으로 만든다. 초기 동시요청/실제 child중단/회수직후 경쟁/살아있는 worker의 느린send/만료/이전worker의 늦은 성공·실패/접수후기록전 중단을 함께 검사한다. 불명확한 외부 접수 결과를 무조건 미전송으로 보고 다시 보내지 않는다. 변수 한 개 수정 후 ready로 끝내지 않는다.

재현:

```bash
TMPDIR=/var/tmp node /var/tmp/codex-night-a005f59-0nyj9qkh/dispatch-reclaim-race.mjs
TMPDIR=/var/tmp node /var/tmp/codex-night-a005f59-0nyj9qkh/dispatch-live-expiry.mjs
```

## M6: writer 배제는 확인됐으나 복구 후 작업은 실패 (P2)

새 `scripts/isolated-m6-writer-cutover.py`는 holder가 `_try_lock`을 유지하고 parent `run_all`에서 already_runningtrue를 확인한다. 이 범위는 실제 두 프로세스의 배제 증거다. 하지만 holder는 stdin 문자를 받아 정상 종료한다. **kill 시나리오가 아닌데 after_kill로 표기**돼 있다.

직접 fixed-source 복사본에서 원래 동작에 결과 관찰만 추가했다 (`m6-observe.py/.json`). 해제 후 실제 `run_all`: **statusfailed, pages0, errors1, exit_code1**, `SafeSourceFilesystemError: source mutation observed: .`. script는 already_runningfalse만 검사하므로 EXIT0을 낸다. 이 EXIT0은 복구 후 업무 성공이 아니다. 기본 fixture source 설정의 영향이 있으므로 이를 곧바로 운영 제품 장애로 일반화하지 않는다.

검토용 복사본에서 명시적 inbox/deny source와 새 합성문서를 설정한 추가 시도도 pages0/exit1이었다 (`m6-corrected-config.json`). 이것 역시 제품 소스 변경이 아니라 fixture 진단이며 성공으로 집계하지 않았다. Grok는 올바른 입력/설정에서 실제 post-recovery 업무의 성공과 커밋된 결과까지 이어서 입증해야 한다.

store-blind previous는 여전히 false JSON을 출력하는 stub이고 `cutover:false`라 실제 전환실패→복구 경로는 없다. 운영 drain을 실행하라는 요구가 아니다. **격리된 실제 제품 진입점**에서 writer 배제, 실패한 전환, 안전한 복구, 새 업무 성공, 철회/권한 보존을 함께 끝낸다.

## M12: cold DR/일반 쓰기의 대체 증거 (P2)

새 `tests/test_cold_restore_write.py`를 fixed-source 복사본에서 실행하며 실제 삭제 목록만 기록했다 (`m12-observe.py/.json`). 제거된 파일은 **`.sb/knowledge-registry.sqlite` 하나**다. generation/request/control DB는 생성되지 않았고 원본 vault 트리도 남아 있다. 따라서 live_sqlite_removedtrue는 전체 원본·제어상태 유실 검증을 뜻하지 않는다.

복원 후 “일반 쓰기”는 제품 CLI/MCP/pipeline이 아니라 **`tests.knowledge.commit_page` + `stamp_knowledge`**가 직접 파일/커밋을 만든 것이다. pre/post 검색 hit의 좁은 검증은 통과했지만 제품 쓰기 계약·복원된 authority/원장과의 연결은 미검증이다. 시간도 backup 전에 시작해 post-write 전에 끝나므로 표시된 RTO0.0204초(기존 제출0.0225초)는 서비스가 업무 가능한 상태로 복구되기까지의 시간이 아니다. RPO는 backup timestamp만 있고 데이터 유실 경계를 계산하지 않았다.

완료 기준: 대표적인 합성 runtime(세대/요청/control journals/철회·삭제 이력)을 실제 backup 경로로 보관→복구 자료 경계 명시→원본/제어DB 유실→제품 recovery 경로 복구→신규 정상 제품 write/read→삭제 자료 부활 없음과 권한/계보 보존→실제 RPO/RTO 측정. 기존 JARVIS 삭제/복원/2클라이언트 시나리오는 보존하되 이 요구를 대신하지 않는다. 운영 원본/인증에 접근할 필요가 없는 fixture 작업이다.

## 직접 검사와 보존된 범위

- JARVIS focused **8tests passed**, 전체7.88s/테스트4.78s (`jarvis-focused.log`). 직접 tsc EXIT0, Ruff EXIT0. SB 타입0errors/2warnings/EXIT1(os.write 반환 미사용)이며 완전 타입 통과 아님.
- 설치 standard/work/maintenance **3게이트 EXIT0** (`installed-*.log`).
- 정상nested sends1, 설정철회 sends0, 초기동시samekey sends1, deny/옵션/transport 정정후성공, invalidtask send0, callback재시도철회 거부를 실제 제출 dist에서 재확인 (`gjc-lifecycle.json`, `dispatch-recovery.json`, `gjc-fence-confirmation.json`, `dispatch-boundaries.json`, `factory-session.json`). 회수된 lease/만료경합은 위와 같이 미통과다.
- SB 같은 제품/휠 바이트의 과거14focused/marker/다중프로세스 lock 증거는 보존하고 전체 회귀를 불필요하게 재실행하지 않았다. 새 M6/M12 fixture의 좁은 검사 EXIT0과 실제 미충족 결과를 구분했다.
- Grok 원본 `/var/tmp/sb-full-pytest-8db46c5.log`: **1832passed/2skipped/608.01s/EXIT0**을 읽어 확인. 기존 로그 관찰이며 Codex 직접 전체 실행 수치가 아니다. SHA256 `c95170632f5360e280b4f52005a47e77d2a804623a3466a62a385dd0be351bd5`.

A–F/R1–R7/V1–V5와 CURSOR-HANDOFF7절 M1–M14를 유지한다. V1 실제 선택된 세션/compaction/공개transport 연결, M6/M12 남은 계약을 fixture helper나 native 인증 대기로 치환하지 않는다. N2/N4/M11/기존M12 통과는 이전 보고서의 정확한 경로와 범위 그대로 보존한다. 실제 로그인/native 세션/운영drain/사용자평가 질문 같은 외부 입력은 별도 보류이며 임의 승인하지 않는다. M14는 기존 범위를 넘겨 새 기능을 추가하지 않는다.

## 다음 행동

기존 Grok가 현재 승인된 native 목표에서 회수/만료/늦은 결과까지 포함한 dispatch ownership과 M6 실제 복구후 성공·M12 runtime cold복원을 **함께** 끝낸다. script EXIT0/작은 helper 수정으로 전체 체크리스트를 종료하지 말고 결과·소유권·복구 상태를 확인한다. 필요한 제품 recovery 진입점이나 설정이 없으면 먼저 그 구체 원인을 해결한다. 새 고정 candidate/hash와 통합 증거를 제출하면 같은 Codex 작업이 재검토한다. 30분 감시는 유지하며 운영전환/인증복사/사용자삭제/push/최종인수 승인 없음.
