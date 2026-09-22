# 야간 독립 검토 — 1d3d1d7 미통과

작성자: 기존 Codex 감시 작업 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`, 야간 독립 검증 위임. 원래 Codex 직접 실행 아님. `2026-09-11T17:36:13.252476+00:00`. **제품 준비/운영 최종 인수 아님.**

## 고정 후보와 직접 바이트 검증

제출 `1d3d1d7d8d4bea93b0dfe994f5c6495974cb1edf`, SB source `210226e1fe05bf1fae28f86238f0f4ecf3103f98`. release `0ecdb5617a1fe95697e55366f631ee4373f407b1`, wheel `0e32b787c97a42d922132e93e3c67ab375d06154b433d23a042283112cbf0b57`, 후보 `/var/tmp/sb-candidate-210226e/releases/0ecdb5617a1fe95697e55366f631ee4373f407b1`. archive/휠/설치물182개 Python 바이트 일치. SB 제품 소스는 f94d073과 동일하며 새 변경은 scripts/문서다.

JARVIS `aee8f1f`, dist `/var/tmp/jarvis-artifact-aee8f1f/source/dist`, inventory `5e4de7e96fd435f2f988bca24fe267cfc30d4407c21e5b53569a2afb5e95ef32`/34780. 제품 tracked1137개 Git 소스와 일치, 이번 직접 tsc **EXIT0**, 별도 출력 JS1109개와 제출 dist 바이트 일치. 이전 옛dist/TS2339 문제는 이 후보에서 해소됐다 (`sb-identity.json`, `jarvis-identity.json`, `jarvis-tsc.log`). 직접 설치3게이트의 before/after inventory도 제출 값과 일치했다.

증거/harness `/var/tmp/codex-night-1d3d1d7-wxk5m5cn`. 모든 테스트는 합성 fixture이며 운영 authority/config/auth 복사 없음. 검토 종료 HEAD 고정 제출과 동일. Codex 제품 소스/테스트 변경 없음.

## N1-crash-restart (P1): 전송 전 프로세스 중단 후 영구 pending

`dispatch-crash.mjs`는 실제 public `executeGjcCommand`, 실제 합성 AuthorityDb와 정상 task/context를 사용한다. child가 durable 예약 후 transport에 진입했지만 아직 전송하지 않은 시점에 `process.exit(99)`로 종료한다. 이는 격리 fixture 프로세스만 종료하며 기존 Grok/운영 worker와 무관하다. 부모는 기존 db객체를 닫았고 child 종료 후 DB를 새로 열어 동일 작업을 정상 transport로 재시도한다.

`dispatch-crash.json`:

```text
child_exit=99; transport_entered_before_delivery
retry_sends=0
retry_response={ok:true, duplicate:true}
model_dispatched=false
state=pending, lease_owner=null, lease_expires_at=null
```

`cli-gjc-commands.ts:96-109`의 catch는 프로세스 종료에는 실행되지 않는다. `gjc-intent-store.ts`의 예약은 pending이며 lease/recovery 기한을 두지 않는다. 기존 replay 조건은 pending을 duplicate로 반환한다. 전송된 결과가 없는데 재시작으로도 실제 작업을 이어갈 수 없다. 응답 접수/duplicate를 모델 전달 성공으로 간주하지 않았으며, **정상 재시작 후 미완료 작업 회복이 안 되는 것**이 결함이다.

완료 기준: 예약 소유권과 수명, 전송 전 중단, 전송 중 불명확한 결과, 접수 후 원장 기록 전 중단, 정상 재시작 복구를 하나의 계약으로 구현한다. 명확히 미전송인 경우 안전하게 새 worker가 이어받고, 불명확한 결과는 임의 재전송/완료 처리하지 않는다. 공개 제품 재시작/복구 경로에서 현재 권한·세대·문맥 재검사와 중복 억제를 검증한다. SQLite 수동 변경을 복구로 대신하지 않는다.

재현:

```bash
TMPDIR=/var/tmp node /var/tmp/codex-night-1d3d1d7-wxk5m5cn/dispatch-crash.mjs
```

원본 증거를 보존하려면 harness 복사본에서 실행한다.

## 통과한 정상·실패·정정 범위

이번에는 진단 emit이 아니라 **실제 제출 dist**에서 직접 확인했다.

- 정상 nested dispatch sends1, 설정 기반 철회 key sends0/`MEMORY_READ_FENCE_KEY_UNAVAILABLE`, 동시 같은키 sends1 (`gjc-lifecycle.json`, `gjc-fence-confirmation.json`).
- deny→허용: 0회 후1회 전송. transport실패→정상: 첫2회실패+정정후1회성공=총3회. options없음→설정: 0회후1회성공. 모두 model_dispatchedtrue (`dispatch-recovery.json`). 이전 catch 가능한 실패의 예약 고착은 개선됐다.
- invalid task sends0, 첫실패후철회는 sends1 뒤거부. callback 기반 factory 정상/throw후성공/만료/no_data/deny 결과 보존 (`dispatch-boundaries.json`, `factory-session.json`).
- JARVIS 해당 integration 파일 직접 **7 tests passed**, 전체 실행7.21s/테스트4.42s (`jarvis-focused.log`).
- installed standard/work/maintenance **3게이트 EXIT0** (`installed-*.log`). Ruff EXIT0. Python 변경 없는 revoked_keys 타입 **0errors/2warnings/EXIT1**: os.write 반환 미사용. 완전 타입 통과로 쓰지 않는다.
- SB 제품/휠 바이트가 동일하므로 직전14focused, marker·다중프로세스 lock검사를 이유 없이 재실행하지 않았다. 이전 고정트리/같은 바이트 근거를 보존하며 새로운 테스트 수에 합산하지 않는다.

Grok 전체 원본 `/var/tmp/sb-full-pytest-210226e.log`를 읽어 **1831passed/2skipped/610.70s/EXIT0** 확인. 기존 로그 관찰이며 Codex 전체 회귀 직접 실행 수치가 아니다. SHA256 `f1e0607b26bc35c9e79f8317bb68644e3ff43490bdc47a93975c416b49e6cefc`.

## M6/M12: 반복되는 미완료 통합 근거

**M6 새 script는 아직 helper 테스트다.** `scripts/isolated-m6-rollback-cutover.py:30-35`가 previous `.venv/bin/python`에 `reads_revocation_store:false` JSON을 출력하는 stub을 만든다. 이후 helper의 allowedfalse와 새 후보 allowedtrue를 검사한다. 실제 writer/reader가 실행되지 않고 전환 실패나 서비스/제어상태 복구도 없다. `/var/tmp/m6-rollback-cutover.json`을 읽어 이 범위를 확인했다. stub 자체가 잘못이라는 뜻이 아니라 원 M6 전체 인수 증거가 아니라는 뜻이다.

직전 리뷰에서 generation_writer의 preparing 중 다른 실제 프로세스 busy, fixture 종료 후 acquired는 이미 확인했다. 다음은 실제 격리 제품 진입점의 writer 배제→실패한 전환/복구→동일 권한/철회 상태 유지까지 이어지는 실행 경로다. 운영 drain 허가 없이 가능한 fixture이며 운영 전환을 요구하지 않는다. 구현/런북 중 필요한 복구 진입점이 없다면 무엇이 없는지 먼저 명시하고 승인된 범위에서 해결한다.

**M12는 이전 restore 시나리오 재실행이다.** `scripts/jarvis-restore-acceptance.mjs`는 현재 provider와 control DB를 유지한 채 backup→삭제→restore→2클라이언트/개별철회→재삭제→restore를 실행한다. `/var/tmp/m12-aee8f1f-restore.out`의 RESTORE0을 관찰했고 그 통과를 보존한다. 기존 소스와 같으며 원본/제어DB 유실을 만들지 않고 복원 후 신규 일반 업무쓰기/RPO/RTO를 확인하지 않는다. 이 로그를 cold DR 완료로 바꾸지 않는다.

다음 독립 작업은 별도 합성 fixture에서 복구 자료 경계를 선언하고, 모든 live 프로세스를 정상 정리한 후 원본/제어DB가 없는 상황→실제 backup 복원 진입점→신규 일반 업무의 정상 write/read→철회된 자료 부활 없음→RPO/RTO/남은 자료 의존성을 확인하는 것이다. 필요한 복구 경로가 아직 없다면 그 원인을 해결한다. 운영 원본 삭제나 운영 인증 복사는 금지다.

## 원 요구와 남은 조건

A–F/R1–R7/V1–V5 및 CURSOR-HANDOFF7절 M1–M14의 의미를 유지한다. 앞선 N2 검색·N4 실제 UI 실패→정정→pages1/실패이력, M11 실제 MCP와 샘플 RSS, M12 격리 공유복원 통과는 각 고정트리와 경로에 한정해 보존한다.

V1/M9의 실제 선택 세션/compaction 연결은 더 넓은 최종 인수가 아니다. `personal-context-persistence.ts:58`은 capture session을 `session:${now}`로 만들며 task.session_id와의 대응은 이번 fixture가 입증하지 않는다. 기본 options 없는 CLI 경로는 여전히 `MEMORY_REFERENCE_OPTIONS_REQUIRED`, fallback은 RecordingModelTransport다. 위 callback/설정형 fixture 정상 전송을 실제 native 세션 인수로 바꾸지 않는다. live 인증 없이 가능한 공개 진입점 계약을 끝내고 실제 사용자/native 인증이 필요한 부분만 외부조건으로 남긴다.

실제 로그인/native 세션·운영 drain/전환·사용자 평가질문 등의 외부 입력은 정확히 기록해 오전 보고에 모은다. 이번 중단은 외부 입력만 남은 것이 아니다. M14는 기존 범위 그대로 유지하고 새 기능을 추가하지 않는다.

## 재개 요구

기존 Grok의 현재 승인된 native 목표에서 위 **프로세스 중단/재시작과 M6/M12 실제 통합 시나리오**를 완료한다. 현재 실패가 예외 catch 경로뿐이라면 test만 추가하지 말고 실제 소유권/복구 계약을 해결한다. helper 수정/기존 테스트 재실행 뒤 goal완료를 반복하지 말고 남은 실행 가능한 체크리스트의 종료 근거를 확인한 뒤 새 후보를 제출한다. 새 source/wheel/설치물/JARVIS/harness 핀과 한정된 통과/외부조건을 일관되게 제출하면 같은 Codex 작업이 독립 재검토한다. 30분 감시 유지. 운영 전환/인증 복사/사용자 삭제/push/최종 인수 승인 없음.
