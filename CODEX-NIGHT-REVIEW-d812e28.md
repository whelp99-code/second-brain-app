# Codex 야간 독립 검토 — d812e28

**미통과. 전체 인수 아님.** 이전 missing/junk backup 실패 시 기존 DB 삭제 문제는 해결됐다. 그러나 실제 child 비정상 종료로 WAL이 남은 대상에 복원하면 성공을 반환하고도 다시 연 DB에서 이전 데이터가 읽힌다. JARVIS RPO에 다른 시스템의 기록을 대응시킨 증거 문제와 복구 준비·원 요구 상태표의 미충족도 남아 있다.

작성자는 기존 Codex 감시 작업 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`다. 원래 Codex가 직접 실행한 것으로 쓰지 않는다. UTC 2026-09-12T00:35:40.865442+00:00. 정본 A–F/M1–M14, 26cf158/d26dd7a 및 6a1dcc0 검토를 이어받는다. 모든 장애/복원 재현은 새 합성 fixture에만 수행했다.

## 고정 대상과 직접 검증

- SB submission `d812e284af28a34a6ece5905caee6f8544577a92`, source `a1a5ae2a7e0495117790bf03f14a42bbbe67760c`, release `0ecdb5617a1fe95697e55366f631ee4373f407b1`, wheel `0e32b787c97a42d922132e93e3c67ab375d06154b433d23a042283112cbf0b57`.
- 설치물 `/var/tmp/sb-candidate-a1a5ae2/releases/0ecdb5617a1fe95697e55366f631ee4373f407b1`. archive/wheel/설치 Python182개 동일.
- JARVIS `22b46139e312979e6ac81b41ef4b8c64a4d2d71a` / `/var/tmp/jarvis-artifact-22b4613/source/dist`. product tracked1137개 동일, 독립 tsc 재빌드 JS1109개 동일.
- inventory `6f30a34af67aec7587ef1bfdb046c29645cc0e5508030ce4be13d08711a7b868` /34768 entries, 검사 전후 동일. Vitest는 후보를 변경하지 않는 별도 복사본에서 실행했다.
- 모든 harness/원본 로그: `/var/tmp/codex-night-d812e28-p3dzqr9w`. `run-checks.py`, `restore-failure-preservation.mjs`, `restore-orphan-wal.mjs`, `source/scripts/codex-restore-observe.mjs`. paired 사본은 정본의 Python interpreter 경로만 venv로 바꿨다.

직접 backup integration **5 passed /335ms /EXIT0**, Ruff0, JARVIS tsc0, 설치 standard/work/maintenance **3게이트 EXIT0**. `jarvis-backup-tests.log`, `ruff.log`, `jarvis-tsc.log`, `installed-*.log`. revoked_keys 타입은 0errors/2warnings/**EXIT1**이며 전체 타입 통과가 아니다. 변경하지 않은 dispatch의 이전30개나 전체 SB pytest를 반복하지 않았다. 기존 로그 수치를 이번 직접 실행 수치와 합산하지 않는다.

`restore-failure-preservation.json`: invalid/missing backup + 기존 sentinel DB 모두 오류 뒤 SHA보존. invalid 새 대상 거부와 정상 새 대상 quick_check/내용 일치도 유지한다. 기존 P1의 이 재현은 해결로 기록한다.

paired 정본과 추가 같은-ROOT 명령은 EXIT0. DB 유실/restore, scoped2·독립 철회2·새write proved·highwater2/재복원0을 유지한다. writer_busy=true, 실제 journal pending_requests0/empty_queuetrue로 이전 파일 개수 문제는 해결됐다. `recovery.env`의 BACKUP/DEST/JARVIS를 넣은 `restore-jarvis-sqlite.mjs`와 즉시 같은 fence2로 실행한 SB restore도 직접 EXIT0이다. 이번 격리 RTO restore→read2324ms, 장애→read9288ms, →scoped+새write11837ms, JARVIS unlink→reopen34ms, 전체scenario20800ms다. 운영 인수로 확장하지 않는다.

## M12-restore-orphan-wal / P1 — 성공 반환 뒤 실제 내용이 백업과 다름

`restore-orphan-wal.mjs/.json`이 실제 child에 SQLite WAL 모드와 autocheckpoint0을 설정하고 sentinel=`old-destination-unrecovered`를 commit한 뒤 **exit99**시킨다. dest-wal/dest-shm이 남은 것을 확인하고, sentinel=`backup-approved`인 정상 백업을 제품 `restoreSqlite`로 복원한다.

결과: restore는 quick_check **ok**,8192bytes와 SHA를 반환한다. 하지만 새 readonly SQLite 연결의 SELECT는 **old-destination-unrecovered**를 반환한다. 기대했던 backup-approved가 아니다. fixture `/var/tmp/codex-restore-wal-kV3SZ7`에 보존했다. 함수의 `src/personal-os-backup.ts:148–155`는 staging만 검증하고 main파일만 rename하며, 대상 WAL/SHM 및 writer 상태를 함께 다루지 않는다.

완료 기준: 정상/실패/정정과 같은 복구 계약에서 live writer 및 orphan WAL/SHM을 함께 다루라. SQLite 파일 세트와 쓰기 배제를 보장할 수 없는 대상은 안전하게 거부하거나 검증된 복구 절차를 거쳐야 한다. 기존/백업 데이터 보존을 유지하고, 실제로 다시 연 목적 DB의 내용/철회 상태까지 확인한 뒤 성공을 반환하라. WAL을 무조건 삭제하는 처방이나 운영 DB 시험은 승인하지 않는다.

## M12-rpo-provenance / P2 — SB 기록을 JARVIS 유실 receipt로 기재

`seed-extra-lost.py`는 SB RequestExecutor에 합성 remember를 accepted/proved로 기록한다. `jarvis-restore-acceptance.mjs:68–77`은 그 request_id를 extraDeleted의 request_id와 proof_id 양쪽에 넣는다. 이는 실제 JARVIS accepted receipt와 proof를 만든 경로가 아니다.

직접 결과의 JARVIS backup/extra/restore counts는 모두 tombstone_chain1/deletion_proofs0/gjc_intents0이다. 그런데 `lost_accepted_present_after_restore=false`는 상수이며 lost_accepted_proof_id에는 memreq ID가 들어 있다. 별도 readonly SQLite 조회(`rpo-receipt-provenance.json`)에서 그 요청은 **SB journal에 state=proved, 실제 proof_json과 함께 남아 있었다**. SB 복원 후 ExtraLost 본문이 사라진 것은 유효한 데이터 손실 관측이지만 JARVIS accepted receipt 유실로 치환할 수 없다. 현재 상태표의 accepted forget 유실1도 코드/결과와 다르다.

완료 기준: 기존 JARVIS의 실제 accepted 효과/요청 저장 경로를 이용해 백업 전후 durable row와 진짜 proof ID를 확보하고, 파일유실 후 복원된 ID집합을 비교하라. SB 본문 손실/SB receipt 잔존/JARVIS receipt 손실을 각각 구분한다. countReceipts의 오류를0으로 숨기는 처리를 없애 검증 불능을 실패로 기록하라. 백업 이후 철회/권한 변경이 있을 때 stale 복원 상태로 재승인·재노출·중복 실행되지 않는지도 같은 경로에서 완료한다. 별도 새 기능을 만드는 지시가 아니라 기존 복구 계약과 원장 계보 검증이다.

## B-F-recovery-preparation / P2 — 즉시 재현 통과와 장기 복구 준비 구분

현재 fence2를 마지막에 써서 **즉시** 같은 ROOT 복원하는 경로는 해결됐다. 그러나 런북은 여전히 발급된 파일을 나중에 재사용하며, 유효시간이 지난 이후 현재 권한/최신 high-water를 검증하여 새 fence를 발급하는 실행 절차가 없다. 제품 verify_read_fence는 최대5분 수명을 검사한다. 미래 실행의 성공을 이번 즉시 성공으로 주장하지 말고 실제 fresh 발급/거부/정정 절차를 준비하라.

old-schema 시험은 sentinel 테이블만 만든 정상 SQLite를 restore한 뒤 tombstone_chain이 없음을 확인하는 helper다. 이는 실제 과거 지원 버전의 호환 확인이나 제품의 unsafe rollback 거부가 아니다. 요구한 대상 버전/스키마의 읽기·철회 상태 보존 또는 안전한 거부·복구 경로를 격리에서 검증하라. 운영 전환 허가는 여전히 별도다.

## requirements-mapping / P2 — 원 의미의 전체 범위와 근거 필요

A–F와 M1/M2/M14 명칭 정정은 개선됐다. 하지만 M4는 **검증 결과 원계보**인데 모델 문맥 계보로, M7은 **전체 읽기 범위**인데 이전 경로로, M8은 **제품별 공유연결**인데 세션 resolver/issuer로 축소됐다. M6는 단일작성자·전환복구 전체이며 generation.lock 한 시험으로 대체하지 않는다. M14 관계검색의 상태는 generic 격리 검색 경로를 근거로 implemented_unverified가 되었으나 요구된 추가 가치·비용·삭제 일관성 평가가 아니다.

CURSOR-HANDOFF §7의 원 요구 문구/범위를 보존한 표에 각 직접 증거 링크, 실제 미구현, 구체적 외부 입력을 연결하라. M14 효과가 없으면 근거 있는 보류가 가능하다. M3 철회, M13 전체GUI 등 다른 요구도 한 하위 경로나 불특정 운영 입력으로 축소하지 않는다. 사용자 인증/실사용 GT/운영 corpus 부족은 해당 범위의 조건이며 독립 구현 전체의 blocker가 아니다.

## 다음 행동

기존 Grok의 현재 승인 native goal을 공식 기능으로 재개하고 **SQLite 복구 전체 계약, JARVIS 실제 durable 계보/RPO, 실행 가능한 fresh-fence/버전 복구 절차, 원 요구표**를 함께 마친 뒤 일관된 hash의 새 후보를 제출한다. 이전 dispatch 통과 범위 보존, 불필요한 전면 재검사 금지. 운영 전환·인증 복사·실사용자 삭제·push는 승인하지 않았다. 기존30분 감시는 유지한다.
