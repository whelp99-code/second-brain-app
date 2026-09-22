# 야간 독립 검토 — c3e1d9f 미통과

작성자: 기존 Codex 감시 작업 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`, 사용자 야간 독립 검증 위임. 원래 Codex가 직접 실행한 결과가 아니다. 완료 시각 `2026-09-11T16:40:19.865764+00:00`. **제품 준비/운영 최종 인수 아님.**

## 고정 후보와 실제 바이트

- 제출 `c3e1d9f19dd9fd991dd9611b0935e5e78304ad87`, SB source `f40291839792d6243996490e093dfdacd269c4cc`.
- release `0025ebe27ec7091c2a824d1594c51bc2537b1423`, wheel SHA256 `ba7713566a93cea4bcee69a81d87e8560bb943efe897cc37269e1e2d7e3c860f`.
- 후보 `/var/tmp/sb-candidate-missing-state/releases/0025ebe27ec7091c2a824d1594c51bc2537b1423`.
- JARVIS `37b034ff8d87e6e6a28c07cefb3165a4f2a4ed4a`, dist `/var/tmp/jarvis-artifact-37b034f/source/dist`.
- inventory `020927977dce50e1f5dd98de59c2a5d70ae0ef7ec1ccbc0215b03f3c1ea0bc53`, 제출 entries34780. archive/휠/설치물 Python182개 일치. JARVIS tracked1134개 일치, 직접 tsc 재빌드 JS585개와 제출 dist 바이트 일치. `sb-identity.json`, `jarvis-identity.json`.
- 검토 종료 시 제품 HEAD는 제출과 동일. 제품 소스/테스트 수정 없음. 운영 current41f0751은 제출 상태이며 이번 리뷰가 운영을 전환하거나 별도 운영 인수를 수행하지 않았다.

원본 증거와 재사용 harness: `/var/tmp/codex-night-c3e1d9f-yhvbbfzq`. 각 JSON은 실제 직접 실행 결과다. 합성 DB/authority/transport만 사용했으며 운영 인증은 복사하지 않았다.

## 실행 가능한 결함 — 하나의 lifecycle로 수정 필요

### N1-configured-authority (P1): 설정 기반 철회 검사 생략

`src/cli-gjc-commands.ts:195`는 `AssembledModelSession`을 직접 만들고 `options.read_fence?.`와 `status_fence?.`만 호출한다. 지원하는 `read_fence_config`로 production fence를 만드는 기존 경로를 사용하지 않는다.

`gjc-fence-confirmation.json`: 정상 DB/task와 합성 signing key를 만든 뒤 실제 제품 API로 철회했다. 같은 config의 `createProductionMemoryReadFence`는 `MEMORY_READ_FENCE_KEY_UNAVAILABLE`로 거부한다. 그러나 그 config를 넘긴 실제 `executeGjcCommand`의 nested dispatch는 **sends1/oktrue**다. helper 단독 결함이나 live 유출을 주장하는 것이 아니라 실제 CLI handler의 설정 계약 누락이다. 추가 `gjc-lifecycle.json`에서 정상 sends1, 기본 dependency 없는 호출은 `MEMORY_REFERENCE_OPTIONS_REQUIRED`/sends0이다. Recording fallback도 실제 native 세션 전송의 인수 증거가 아니다.

완료 기준: 공개 dispatch/session 진입점에서 설정·callback 모두 동일한 현재 권한/세대 검사를 사용하고 실제 선택된 task session 및 전송과 결합한다. 정상/무효/철회/만료/no_data/새 세션/compaction/실패 재시도 계약을 통합 검증한다. 운영 로그인 없이 가능한 production factory + 격리 transport를 사용한다.

### N1-concurrent-idempotency (P1): 같은 작업이 두 번 전송됨

`src/cli-gjc-commands.ts:94-100`의 조회→비동기 send→intent 생성 순서에서 동일 키의 두 호출이 함께 조회를 통과한다. `gjc-lifecycle.mjs`는 두 전송을 rendezvous로 묶으며 sleeps 없이 실제 handler/DB를 실행한다. **sends2**, 반환 intent_id는 동일하다. 직렬 duplicate 테스트의 sends0만으로 동시 재시도 안전성을 입증할 수 없다.

완료 기준: 유효성/권한 확인, durable 작업 예약, 전송 결과와 불명확한 실패, 동시 중복, 재시작/재시도 복구를 하나의 상태 수명으로 연결한다. 응답만 duplicate로 바꾸는 것으로 해결하지 않는다. arbitrary 외부 시스템의 무조건 exactly-once를 요구하는 것은 아니며, 현재 제품의 동일 작업 중복 전송과 원장 기록 간 불일치를 해결해야 한다.

### N3-reader-writer-recovery (P2): 서로 다른 lock으로 marker 경합

`sb/revoked_keys.py:108` reader는 `.revoked.lock`, `:123` writer는 `revoked-jarvis-signing-key-ids.lock`을 잠근다. `_write_marker:37-56`은 동일 `.initialized.tmp`를 unlink/replace한다.

`reader-writer.py/.json`: writer가 key:b 추가 중 marker tmp를 연 직후 정지시키고 reader를 실행한다. reader가 journal을 복구하면서 tmp를 교체하므로 writer의 replace가 **FileNotFoundError**로 실패한다. 최종 key:a/key:b는 보존되므로 이번 재현을 철회 키 부활로 과장하지 않는다. 정상 읽기와 동시 철회 쓰기의 안정성 결함이다.

완료 기준: 읽기·쓰기·journal 복구의 공통 소유권/잠금, 안전한 tmp 수명, 지속성을 일관되게 구현한다. 다중 프로세스 read/write, 중단 지점별 재시작, 새 key 누락 없음, 기존 안전 거부를 같이 검사한다. 기존 harness는 잘못된 서로 다른 lock의 interleaving을 강제한다. 수정 후 같은 lock을 쓸 때 harness 대기를 그대로 유지해서 생기는 timeout은 제품 결함으로 세지 말고 올바른 동기화 검사로 바꾼다.

## 직접 통과/검사 한계

- 변경 범위 pytest **24 passed, 19.32s** (`focused.log`), Ruff EXIT0 (`ruff.log`).
- 변경 Python 파일 타입 검사 **0 errors/2 warnings, EXIT1** (`python-types.log`): `os.write` 반환 미사용 52/138행. 타입 게이트 완전 통과로 표현하지 않는다.
- JARVIS tsc EXIT0 및 재빌드 바이트 비교 통과 (`jarvis-tsc.log`, `jarvis-identity.json`).
- 실제 설치물 standard/work/maintenance 게이트 3종 EXIT0 (`installed-standard.log`, `installed-work.log`, `installed-maintenance.log`).
- 이전 invalid dispatch는 sends0, 첫 실패 후 철회하면 sends1 뒤 거부로 개선 (`dispatch-boundaries.json`). callback을 실제 제공한 factory 정상/실패1회 후 성공/2회 실패/throw 후 성공/만료/no_data/초기 deny 통과 (`factory-session.json`). 이는 위 config 우회까지 통과했다는 뜻이 아니다.
- 빈 state_root, truncation, legacy 완전 줄 유실의 안전 거부, journal 기록 후 marker 교체 중단→복구/재시도 결과 보존 (`partial-truncation.json`, `marker-lifecycle.json`, `extended-result.json`). 동시 reader/writer는 위와 같이 미통과다.
- Grok 원본 `/var/tmp/sb-full-pytest-f402918.log`를 직접 읽어 **1830 passed,2 skipped,632.33s,EXIT0** 확인. 이는 기존 로그 관찰이며 Codex 전체 회귀 재실행 수치가 아니다. SHA256 `20be799fae18a536fbf34f36f95bd4fdc948c4a793457b3c7e9b4f5f69530d1e`. 이번에는 변경 범위와 새 경계 결함을 직접 검사해 동일 고정 트리의 전체 회귀를 불필요하게 반복하지 않았다.

재현(산출물 원본을 보존하려면 harness를 새 디렉터리로 복사):

```bash
TMPDIR=/var/tmp node /var/tmp/codex-night-c3e1d9f-yhvbbfzq/gjc-lifecycle.mjs
TMPDIR=/var/tmp node /var/tmp/codex-night-c3e1d9f-yhvbbfzq/gjc-fence-confirmation.mjs
TMPDIR=/var/tmp PYTHONPATH=/var/tmp/codex-night-c3e1d9f-yhvbbfzq/source /home/jm/orca/projects/second-brain-app/.venv/bin/python /var/tmp/codex-night-c3e1d9f-yhvbbfzq/reader-writer.py
```

## 기존 A–F/M1–M14 범위 유지

원 요구는 CURSOR-HANDOFF 7절 그대로이며 N1/N3은 검토 결함이다. 새 제품 요구로 바꾸지 않는다. N2 검색 개선, N4 실제 UI 실패→설정 정정→동일 경로 실행 성공/실제 pages1 및 과거 실패 보존은 이전 고정 후보 리뷰에 남아 있다. 이번 후보의 새 전체 인수로 복제하지 않는다.

`CODEX-NIGHT-REVIEW-7d97af7`의 직접 MCP30/100/300 기존 page mutation→옛 needle0/샘플링한 서버 RSS, JARVIS 삭제→복원→동시2클라이언트/개별 철회→재삭제→재복원 통과는 보존한다. 원 사용자 정정 진입점/계보·전체 RPO/RTO·원본/제어 DB를 잃은 cold DR·복원 후 신규 일반 업무 쓰기까지 통과한 것은 아니다.

**M6 상태표의 verified 근거는 부족하다.** `test_rollback_compat.py`가 전체 회귀에 있다는 것은 compatibility helper 검증이다. `deploy/check-rollback-compat.py`의 제품 전환/복구 호출 경로는 이번 소스 검색에서 찾지 못했고 기존 런북에는 수동 명령만 있다. 실제 운영 drain은 승인 대기이지만, 격리 writer 배제→전환 실패→현재 버전과 revocation-aware 복구 경로의 통합 rehearsal까지 막힌 것으로 확대하지 않는다. **M12** 위 cold DR/복원 후 일반 쓰기와 측정 근거도 이어서 완료해야 한다.

M5의 “인증 복사 금지”는 금지 행위이지 외부 입력의 이름이 아니다. 실제 필요한 native 로그인/사용자 세션과 인증 없이 가능한 사본 수명 fixture/제품 진입점 검증을 분리해 정확히 기록한다. M1/M2/M8 실제 사용자/native 인증, 사용자 평가 질문, 운영 drain/전환은 외부 조건으로 남으며 잠든 사용자에게 반복 요청하거나 임의 승인하지 않는다. M14 기존 범위를 유지하며 새 기능을 추가하지 않는다.

## 다음 행동

기존 Grok가 현재 승인된 native 구현 목표를 이어가며 위 dispatch 전체 lifecycle와 revocation read/write/crash recovery, M6/M12 실행 가능한 통합 근거, 전체 A–F/M1–M14 상태표를 함께 마친다. helper 한 곳 수정 후 ready를 반복하지 않는다. 새 일관된 source/release/wheel/JARVIS/harness 핀과 해결·미해결 근거를 제출하면 같은 Codex 감시 작업이 재검토한다. 운영 전환/인증 복사/사용자 기록 삭제/push는 하지 않는다. 30분 감시는 유지한다.
