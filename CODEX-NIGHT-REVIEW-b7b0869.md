# 야간 독립 검토 — b7b0869 미통과

작성자: 기존 Codex 감시 작업 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`, 위임된 야간 독립 검증. 원래 Codex 직접 실행 아님. 2026-09-11T23:05:05.165006+00:00. 제품 준비/운영 인수 미완료.

## 고정 후보 / 바이트 검증

제출 `b7b086935ba7a0841a7d321de1ffe4c226871f4a`. SB source `39ce670d1df23361189e14e85548bfbfbe411117`, release `0ecdb5617a1fe95697e55366f631ee4373f407b1`, wheel `0e32b787c97a42d922132e93e3c67ab375d06154b433d23a042283112cbf0b57`. 후보 `/var/tmp/sb-candidate-39ce670/releases/0ecdb5617a1fe95697e55366f631ee4373f407b1` × JARVIS `2a95f72a9dddd510fda90ae942858edda2c0fc9a` / `/var/tmp/jarvis-artifact-2a95f72/source/dist`.

SB182 Python archive/휠/설치물 동일. JARVIS 제품 tracked1137파일 동일, tscEXIT0 / 재빌드1109JS 동일. 전체 inventory `452bf35293453cbcc45bebff40bf7b9edfefe3ad34d8126dd3a4a14c616e161e` /34768은 제출값 및 검사 전후 동일하다. dispatch JS `246bca542e0ce3737165e8e3d3b18ef9773202bee048364537b1f458c2feb9b0`도 일치한다. 증거 `/var/tmp/codex-night-b7b0869-k59c5qay`. 테스트는 독립 전체 복사본, 재현은 제출 dist를 사용했다. 제품 소스/테스트/운영 변경 없음.

## 직전 V1-C/D/E 재현 통과

- **예산:** 기존 total2048/excerpt128 초과 사례는 기억을 제외하고 omission을 남긴250bytes/no_data로 전달하여 각 한도 준수. 원문을 임의96자로 자르는 방식으로 돌아가지 않았다. `dispatch-final-budget-2048.json`.
- **영속 문맥:** 서로 다른 본문/출처 2건을641bytes로 보내고 SQLite memory_count2/evidence_count2/binding2, last capture가 실제 전송과 일치한다. `dispatch-persisted-lineage.json`.
- **전송 전 거부 복구:** 마지막 revalidate에서 generation이 바뀌면 첫 send0으로 거부되고, 정상 provider로 정정한 동일 요청은 실제send1로 성공한다. 이전 unknown_accepted/send0 고착 해소. `dispatch-before-send-generation.json`.
- **N1:** 실제 자식 프로세스에서 inner negative→accepted 후exit99→다음 프로세스 재시도는 remote접수1/retrysend0/unknown을 유지한다. `dispatch-inner-negative-crash.json`.
- **실제 읽기 경로:** 정상1건419bytes, no_data223bytes, 이미 만료된 record send0, 구성된 새 세션은 새 조회/선택/전송. 첫 negative 후 generation 변경은 두 번째 send를 거부한다. `dispatch-current-reader.json`, `dispatch-newsession-generation.json`.

이 통과는 명시적 gjc.dispatch 함수/실제 submitted dist/격리 provider와 injected model transport에 한정하며 native 인증·실제 모델 운영·문맥 compaction 이벤트 인수가 아니다. payload_state insufficient는 fixture의 별도 live-context 요구에 따른 상태로 보존한다.

## 남은 실행 가능한 결함: 동일 본문·출처의 별도 기록 충돌 (V1-F, P2)

`src/cli-gjc-commands.ts:316–333` evidenceForPersist는 ref로 memory를 찾은 다음 evidence를 **digest/source_id/observed_at**으로만 find한다. 같은 본문/출처/관측시각을 가진 두 개의 별도 기록이면 각 ref가 같은 첫 evidence_id를 고른다.

독립 `dispatch-same-content-records.mjs/.json`: 서로 다른 sid와 record_id/record_digest를 가진 유효한2기록을 사용했다. 원본 core의 sid를 바꾸고 정본 canonical+SHA256 규칙으로 record digest를 재계산했다. reader의4회조회 뒤 **PERSONAL_CONTEXT_MEMORY_EVIDENCE_CONFLICT/send0**. 따라서 '2건 통과'는 본문이 다르다는 fixture 조건에 의존한다. 같은 내용의 독립 원계보를 갖는 기록은 실제로 가능하므로 내용의 동일성과 기록의 동일성을 혼동하면 안 된다.

완료 기준: 서로 다른 전체 record/ref를 근거의 고유 식별자에 정확히 대응시킨다. 같은 본문/다른 ref, 같은 출처/다른 버전, 여러 출처/다른 본문을 함께 검증하고, 동명이거나 내용이 같다는 이유로 한 계보를 다른 계보로 합치지 않는다. 기존 최종 예산·저장/전송 일치·철회/만료·known-unsent 복구와 accepted/unknown 중복방지는 보존한다. 동일한 증거를 중복 생성하지 않는 정책이 필요하다면 양쪽 원계보를 추적하는 명시적 동작이어야 한다.

## M12와 최종 준비

정본 paired restore는 interpreter경로만 검토용으로 바꾸어 직접 EXIT0. root `/var/tmp/sb-jarvis-restore-P7zbrz`. 신뢰 backup journal2개 복구→JARVIS삭제/SB복원→삭제0/보존1→scoped2client/동일세대·본문/독립철회2→같은runtime 새 accepted write proved→highwater2/재복원0을 유지한다.

이번 RTO는 restore→첫read **1694ms**, 장애시나리오 시작→첫read **7417ms**, scoped검사 및 새proved write까지 **10328ms**, 전체scenario **16823ms**로 구분됐다. 앞선 '첫 read를 완전 업무 복구로 표시'한 문제는 이격리시나리오에서 개선됐다. 운영 규모/RTO는 아니다.

SB backup후 쓰기0/손실0은 해당 fixture 범위다. JARVIS request/proof ID와 tombstone 보존 근거는 추가됐지만, last_durable_at_ms를 실제 effects.apply보다 먼저 기록하며 JARVIS 자체 장애/복원으로 검증한 RPO가 아니다. crash_loss_after_last_durable=0을 운영 손실0으로 선언할 수 없다. B/F 서비스·설정·백업 hash·구버전 상태 호환 또는 검증된 복구 준비 및 실제 운영 전환은 여전히 별도 미충족이다. 준비 가능 범위와 운영 허가를 구분한다.

## 수치와 외부 조건

직접 GJC22+session6 **28passed /23.95s**(tests19.00s), RuffEXIT0, tscEXIT0, 설치 standard/work/maintenance **3게이트EXIT0**. revoked_keys 타입0errors/2warnings/EXIT1로 완전 통과 아님. 동일 SB 제품의 전체 회귀는 반복하지 않았다. 이전 브라우저/M6/검색/marker 검증은 각각의 고정후보와 해당 경로로 보존하며 이번28개에 합산하지 않는다.

실제 인증 세션 resolver/issuer/gateway, native 사본 수명, 클라이언트별 자동 주입/문맥 compaction, 운영 drain/전환·처분은 아직 인수되지 않았다. 제품별 구체적인 필요한 입력과 준비된 절차/복구안을 오전 보고에 모은다. 이 조건으로 V1-F 등 독립 구현을 차단하지 않는다. A–F/R1–R7/M1–M14 원 의미 유지. 기존 Grok 목표에서 V1-F와 독립 복구 준비를 통합하여 계속한다. 새 worker/인증복사/사용자삭제/운영전환/push 없음. 30분 감시 유지.
