# 실패·미확정 결과가 성공 기억으로 승격되지 않는다 — 실제 업무 본문으로 확인

인계서 8-C 인수 묶음의 1번 항목("원문·업무 ID·프로젝트·**성공/실패 검증 근거**. 실패/미확정 결과를 성공 경험으로 승격하지 않음")과 M4의 음성 조건이다. [계보 인수](REAL-WORK-JARVIS-LINEAGE-2026-09-10.md)가 실제 업무 본문이 **통과**하는 것을 보였다면, 이 문서는 같은 본문이 근거를 잃었을 때 **막히는** 것을 보인다.

## 실행

```bash
node scripts/real-work-refusal-acceptance.mjs \
     /var/tmp/jarvis-current-pair-_mq15nmd/source/dist \
     REAL-WORK-ITEM-2026-09-10.json
```

exit 0. 원본은 [결과 JSON](REAL-WORK-REFUSAL-2026-09-10.json). 본문은 계보 인수를 통과한 것과 **같은** 실제 업무 항목(`second-brain 릴리스 후보 25d49b4 인수 검증`)이고, 케이스마다 근거만 바꿨다.

## 결과 — 10개 케이스, 발행은 1건뿐

| 케이스 | 결과 | dispatch 발행 |
|---|---|---|
| **positive_control** (근거 정상) | `approved` / `VERIFIED_OUTCOME_APPROVED` | **1** |
| no_verification (검증 기록 없음) | `MEMORY_CANDIDATE_AUTHORITY_INVALID` | 0 |
| expired_verification (근거 만료) | `MEMORY_CANDIDATE_AUTHORITY_INVALID` | 0 |
| not_yet_valid_verification (효력 전) | `MEMORY_CANDIDATE_AUTHORITY_INVALID` | 0 |
| **statement_changed_after_verification** | `MEMORY_CANDIDATE_AUTHORITY_INVALID` | 0 |
| worker_assertion | `rejected` / `WORKER_ASSERTION_REJECTED` | 0 |
| model_assertion | `rejected` / `MODEL_AUTHORITY_REJECTED` | 0 |
| unverified_summary | `rejected` / `UNVERIFIED_SUMMARY_REJECTED` | 0 |
| raw_transcript | `rejected` / `RAW_TRANSCRIPT_REJECTED` | 0 |
| open_conflict (근거는 정상, 충돌 선언) | `rejected` / `OPEN_CONFLICT` | 0 |

## 가장 날카로운 케이스

`statement_changed_after_verification`은 **정상 검증을 먼저 발급한 뒤** 저장할 문장만 `exit 0` → `exit 1이지만 성공으로 간주`로 바꾼다. 즉 "실패한 실행을 성공 경험으로 승격"하려는 시도 그 자체다. 근거가 문장에 결합돼 있어 `MEMORY_CANDIDATE_AUTHORITY_INVALID`로 막히고 후보 자체가 생기지 않는다.

## 거부의 두 가지 모양

- **근거 문제**(위 4건)는 예외로 끊긴다. 후보 행이 **생성되지 않고**(`state: null`) dispatch에도 오르지 않는다.
- **형식은 멀쩡하지만 기억 자격이 없는 입력**(아래 5건)은 `state: "rejected"`인 후보로 **기록되고** 고유한 사유가 남는다. 감사 가능한 거부이며 역시 발행 0이다.

이 구분은 의도된 설계로 보인다. 근거가 없거나 어긋난 것은 오류이고, 근거가 멀쩡한데 자격이 없는 입력은 이유와 함께 남긴다.

## 한계

- 신원과 clock은 여전히 fixture(`2026-08-28T12:00:00Z`)다. 실제인 것은 업무 본문과 그것이 통과·차단당한 제품 경로다.
- 이 검사는 **classify 경계**를 본다. 접수·실행·회수까지의 나머지 절반은 [계보 인수](REAL-WORK-JARVIS-LINEAGE-2026-09-10.md)가 덮는다. 두 문서를 합쳐야 M4의 양면이 된다.
- 운영 authority 릴리스에는 `memory classify` 자체가 없으므로(모듈 77개 부재) 운영에서의 재현은 authority 활성화가 선행 조건이다.
- 제품 코드는 수정하지 않았다. 새로 추가한 것은 검사 스크립트 하나다.
