# 야간 독립 검토 — 20e95ae 미통과

작성자: 기존 Codex 감시 작업 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`, 야간 독립 검증 위임. 원래 Codex 직접 실행 아님. `2026-09-11T18:35:04.516674+00:00`. 제품 준비/운영 최종 인수 아님.

## 고정 후보와 바이트

제출 `20e95ae7908463ed7b72e6bc98ed9691517a9258`, SB source `26b06ebaebfccfbb93b1366b5fb64376534777c2`, release `0ecdb5617a1fe95697e55366f631ee4373f407b1`, wheel `0e32b787c97a42d922132e93e3c67ab375d06154b433d23a042283112cbf0b57`. 후보 `/var/tmp/sb-candidate-26b06eb/releases/0ecdb5617a1fe95697e55366f631ee4373f407b1`. SB archive/휠/설치물 Python182개 동일. SB 제품 바이트는 f94d073 이후 동일.

JARVIS `dcd54e9`, dist `/var/tmp/jarvis-artifact-dcd54e9/source/dist`, inventory `9bd9006c92d31aab75b874d827d0dedde8a8a63c16a4feb7ad1cace6ca7533dc`/34780. 제품 tracked1137개 Git 소스와 동일, 직접 tsc EXIT0, JS1109개 재빌드/제출 바이트 일치. 설치3게이트 before/after inventory도 일치. 증거 `/var/tmp/codex-night-20e95ae-kbf1bmih`. 종료 HEAD 고정 제출과 동일이며 제품 소스/테스트/운영 수정 없음.

## N1 불명확한 접수 결과의 재시작 (P2)

**이전 실패는 개선됐다.** 새 owner로 회수하며 회수직후 동시요청 sends1, 살아있는 worker의 시계를61초 전진해도 sends1이다. 실제 child가 전송 전에 종료한 뒤 새 프로세스 재시도도 sends1. 정상/권한거부/설정철회/예외실패 후 정정/초기동시요청 통과를 유지한다.

하지만 `dispatch-accepted-crash.mjs`는 동일한 실제 public handler/DB에서 **합성 remote가 접수를 기록한 직후 child가 local receipt/event 기록 전에 exit99**하도록 한다. 부모가 DB를 새로 열어 재시도하면 remote접수2회, retry send1, local model_dispatchedtrue다 (`dispatch-accepted-crash.json`). 실제 운영 API/인증은 사용하지 않았다. 이전 “아직 전송되지 않은 중단”과 “이미 접수됐을 수 있는 중단”을 현재 pending/죽은PID 정보만으로 구분하지 못한다.

이것을 사용자 기록이 실제 두 번 삭제/수정됐다는 주장으로 확대하지 않는다. 현재 합성 모델 transport의 반복 접수 재현이며, 기존 통합 지시의 응답 유실/불명확 결과 복구 계약이 남았다는 뜻이다. 임의 remote에 대해 무조건 exactly-once를 요구하지 않는다. 가능한 transport의 idempotency/조회·영수증 계약과 durable delivery identity를 연결하거나, 미확정 상태를 명시적으로 복구 가능하게 남겨 blind resend를 피하는 계약을 구현·검증한다. 안전한 미전송 복구를 전부 막는 방식으로 통과시키지 않는다.

```bash
TMPDIR=/var/tmp node /var/tmp/codex-night-20e95ae-kbf1bmih/dispatch-accepted-crash.mjs
```

## M6에서 직접 통과한 새 범위

fixed-source script의 출력/고정 코드 경로만 리뷰 디렉터리로 바꿔 실행했다 (`m6-observe.py/.json`). 실제 두 프로세스: held동안 already_runningtrue→fixture holder SIGKILL→run_all **ok/exit0/commit `f754c3e0ee02488bc490ed04b6add8f86ce827b3`**, key:test보존. 이 로컬 writer 중단 후 제품 업무 재실행은 통과로 보존한다. 이전 실패표기를 반복하지 않는다.

구버전 호환성 부분은 아직 false를 출력하는 Python stub이며 cutoverfalse다. 실제 운영 drain/전환은 미승인이다. 기존 통합 B/F대로 실제 후보가 만든 세대/원장/철회 상태와 구버전 호환성 또는 구버전 자동rollback을 배제한 검증된 복구 절차, **최종 핀에 맞춘 명령/서비스/설정/백업hash/성공실패조건**을 준비한다. 운영 실행 승인과 이 준비 작업을 구분한다.

## M12 개선과 남은 공유 런타임 DR (P2)

`m12-observe.py/.json` 직접 실행에서 `.sb/search.db`, `.sb/ledger.db`, `.sb/runtime-state/reingress.db` 삭제 후 backup복원, pre조회 성공, **제품 inbox→run_all→post조회/커밋 `851e8d0c04794a06916558e3b33c79d564516cd6`**, key:test 보존을 확인했다. 이전 commit_page helper 대체 문제는 개선됐다.

현재 `_cfg`에는 share_root가 없어 legacy vault 경로다. 공유 runtime generation/request control journal을 만들지 않으며 그 소실을 재현하지 않는다. revoked signing key보존은 삭제 tombstone high-water/처분기록/원본 anchor복구와 다르다. 원본트리도 남긴 채 sqlite3개를 삭제했다. 현재 측정0.0693초는 backup전부터 시작해 새 product write전에 끝난다; 전체 업무가능 RTO가 아니고 RPO는 backuptimestamp뿐이다.

원 통합 인계5절E는 **archive무결성→신뢰된 원장/세대결합→복원→조회/범위거부/삭제high-water→새쓰기**, 별도 SB/JARVIS RPO를 요구한다. CURSOR-HANDOFF9절의 RESTORE_SOURCE_ANCHOR_MISSING 안전거부는 우회하면 안 된다.

다음은 기존 `jarvis-restore-acceptance.mjs`/runtimebackup/control-journal fixture를 토대로 복구자료와 trusted anchor를 명시하고, 새 합성 shared runtime의 원본·generation/request journal이 없는 상태에서 실제 restore경로를 실행하는 것이다. 복원 뒤 fresh scoped reader의 정상·범위거부, 삭제기억 부활없음/재유입차단/high-water, 제품 새쓰기, 실제 RPO와 쓰기가능 시점까지 RTO를 확인한다. source anchor가 없다면 안전거부와 필요한 신뢰근거를 정확히 기록하고, 허용된 fixture에서 신뢰근거가 있는 긍정 복원도 검증한다. 현재 legacy 테스트 결과로 대체하지 않는다.

## 직접 검사 수치와 경계

- JARVIS 해당 focused **9tests passed**, 전체8.91s/테스트5.74s (`jarvis-focused.log`). tsc EXIT0, Ruff EXIT0. SB revoked_keys 타입0errors/2warnings/EXIT1(os.write반환 미사용), 완전 타입통과 아님.
- installed standard/work/maintenance **3게이트 EXIT0**. 실제 이번 직접 실행이며 `installed-*.log`에 보존.
- `dispatch-crash`, `dispatch-reclaim-race`, `dispatch-live-expiry`, `dispatch-recovery`, `gjc-lifecycle`, `gjc-fence-confirmation`, `factory-session`, `dispatch-boundaries`는 **실제 제출 dist**에 실행했다. 위 불명확접수 재현과 정상/부정/복구 통과를 구분했다.
- SB 동일 제품 바이트의 과거 focused/marker/lock 회귀는 보존하고 전체를 불필요하게 반복하지 않았다. 새 M6/M12 경로만 직접 검증했다.
- Grok 전체 원본 `/var/tmp/sb-full-pytest-26b06eb.log`를 읽어 **1832passed/2skipped/660.98s/EXIT0** 확인. 기존 로그 관찰이고 Codex 직접 전체회귀 수치 아님. SHA256 `a303ac360daa1cdc1a89477aee12dafcddb3f632a4bb9fde5291d8c56eadd514`.

## 전체 요구와 다음 행동

A–F/R1–R7/V1–V5 및 원 M1–M14 유지. 이전 N2/N4/M11/기존 공유restore의 통과는 각 정확한 경로/고정트리로 보존한다. V1/M9 실제 선택된 세션·compaction 재선택/철회·만료·no_data와 공개transport 연결은 callback/Recording fixture 이상으로 아직 인수되지 않았다. 실제 필요한 native인증과 인증없이 가능한 제품 경로를 구분한다. M1/M2/M5/M8 사용자/native입력, 운영drain, 사용자질문 등 진짜 외부조건은 오전 보고에 모으며 임의 승인하지 않는다. M14 새 기능은 추가하지 않는다.

기존 Grok의 현재 승인된 native 목표에서 **불명확 delivery 복구, shared-runtime cold DR, 실제 세션 경로와 최종 핀의 복구 준비**를 하나의 남은 체크리스트로 마친다. 통과한 M6 writer재실행/legacy복원/회수경합을 다시 작은패치로 고치지 않는다. 이미 실패한 helper 수준 제출을 반복하지 말고 새로운 통합 근거를 갖춰 일관된 후보를 제출한다. 30분 감시 유지. 최종 인수/운영 전환/인증복사/사용자삭제/push 승인 없음.
