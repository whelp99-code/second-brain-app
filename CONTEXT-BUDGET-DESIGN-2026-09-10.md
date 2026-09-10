# M9 문맥 예산·compaction 설계

[인계 보완](CODEX-REPLY-REVIEW-2026-09-10.md) 5.5. 기존 [경계 공백](CONTEXT-DELIVERY-GAP-ANALYSIS-2026-09-08.md)을 운영 authority `a3cbbbe`와 격리 페어 `195b1a7` dist에서 같은 진단 스크립트로 재현했다. 제품 코드를 바꾸지 않았다. 모델 전달·세션 compaction 인수는 없다.

증거: [CONTEXT-BUDGET-DESIGN-2026-09-10.json](CONTEXT-BUDGET-DESIGN-2026-09-10.json).

```bash
node scripts/context-boundary-audit.mjs /var/tmp/jarvis-current-pair-_mq15nmd/source/dist
node scripts/context-boundary-audit.mjs /home/jm/.local/state/orca-jarvis/authority/current/dist
```

두 실행 모두 exit 0, `status=boundary_gaps_reproduced`, `delivery_acceptance=false`. 운영 DB에 쓰지 않았다.

## 재측정

모듈 SHA-256이 **같은 것:** `context-assembler`, `context-assembler-input`, `context-assembler-budget`, `second-brain-adapter-types`.

**다른 것:** `context-assembler-sources` (ops `14db86cc…` / pair `026e0be4…`). 소스 배선만 다르고 아래 공백의 관측값은 동일했다.

| ID | 관측 (운영=페어) | 설계 결정 |
|---|---|---|
| C1 | `sufficient`인데 `excerpt_present=false`. refs 1 | snapshot 생성을 모델 전달로 치지 않는다. 전달 경계에서 record 본문을 붙인 뒤에만 회수 증거 |
| C2 | provider trust `untrusted` → refs 0, `UNCONFIRMED_MEMORY` | `untrusted`를 confirmed로 올리지 않는다. 검색된 기억을 실행 성공으로 쓰지 않는다 |
| C3 | LF/CRLF/CR/tab 본문 → `CONTEXT_ASSEMBLER_INPUT_INVALID` | SB V3 여러 줄 원문을 이 조립기에 직접 넣지 않는다. mapping 계층에서 본문/식별자를 분리 |
| C4 | excerpt 3B와 3600B의 snapshot이 **둘 다 1967B** | 예산은 최종 전달 payload 바이트(구분·출처 포함). snapshot JSON 크기는 token 예산이 아니다 |
| C5 | 기억만 있으면 `LIVE_LINUX_REQUIRED`로 insufficient | 추천 프로필과 기억 조회 프로필을 나누다. 가짜 live observation을 만들지 않는다 |
| C6/C7 | 이번 probe 범위 밖 (스크립트 limits에 명시) | compaction epoch·삭제 후 재공급은 [M5 사본 정책](M5-COPY-POLICY-2026-09-10.md). 전달 이력 없이 중복 억제하지 않음 |

## 쓰기 비용과의 관계

[M11](M11-WRITE-STAGE-TIMING-2026-09-10.md)에서 운영 규모 `remember`의 대부분은 `_fsync_tree`다. 문맥 팩을 키우거나 줄이는 것으로 클라이언트 MCP 타임아웃(약 18–26s 쓰기)을 해결하지 않는다. 예산 설계는 **조회 주입 비용**만 다룬다.

## compaction

조립기 probe는 세션 중복·삭제·compaction을 검사하지 않는다. 설계:

1. 전달 확인 전의 payload는 compaction 대상이 아니다.
2. 새 session/compaction epoch에는 필요한 record를 다시 고른다. 이전 snapshot id만으로 전달 완료를 주장하지 않는다.
3. 삭제·철회된 digest는 재공급하지 않는다. 클라이언트 로컬 사본은 M5.

## 완료로 올리지 않는 이유

JARVIS 코드를 고치지 않았고, 실제 모델 요청·프로젝트 격리·compaction 후 재공급을 이 실행에서 하지 않았다. 공백 재현은 B5/M9 완료가 아니다.
