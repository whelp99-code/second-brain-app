# 실제 native 작성 호출 → 자비스 완료 → 별도 native 회수

직전 [공개 쓰기→실제 읽기 인수](SCOPED-WRITE-TO-NATIVE-READ-2026-09-09.md)에 실제 작성 클라이언트를 연결했다. 이번에는 Claude Code2.1.261의 첫 실행이 공개 `sb_write_request`를 호출하고, 다른 agent의 새 로그인·별도 Claude 실행이 완료된 기억을 읽었다. [구조화 결과](NATIVE-SCOPED-WRITE-READ-2026-09-09.json).

## 무엇을 완료했는가

| 구간 | 실제 증거 |
|---|---|
| 작성 클라이언트 | Claude tool_use/tool_result1쌍. 제출 JSON이 원래 검토된 요청과 canonical 비교로 동일. accepted의 요청/시각/해시 결합 검사, replayed=false |
| 저장 | 공개 SB MCP→실제 TLS 권한 검사→일반 CLI apply-requests, provider proved |
| 자비스 완료 | 같은 outbox의 실제 인증 reconcile→원작업 completed/outbox settled. 재조회 replay, settlement1/attempt1/FK0 |
| 새 세션 회수 | writer `agent:fixture`와 다른 `agent:reader`, 다른 cookie. 검색 record의 세대/내용을 원래 요청 증명과 대조 |
| 읽기 클라이언트 | 독립 stdio2개+별도 Claude Code2.1.261 실제 tool1회에서 각각2records 회수 |
| 권한 경계 | reader 철회403. 수락 중 철회는 원장 수락 없음, 실행 전 철회·만료는 실패·활성 세대 없음 |

전체4상태 인수가 exit0으로 끝났다. 쓰기 검증 HTTPS 호출 수는 정상5/수락 중 철회2/실행 전 철회3/만료3이며 모두 전송시도1/FK0이다. 정상 읽기 TLS는 별도로3회다.

작성 모델이 자유롭게 만든 문장을 작업 성공 증거로 바꾸지 않는다. 입력 내용·검증된 작업·범위 검토는 기존 fixture가 준비하고 모델은 그 요청을 정확히 제출했다. 작성자의 완료 문장 대신 실제 MCP 수락을 확인하며 수락은 저장 완료와 구분한다. 요청 수정, 다른 도구 호출, 재호출, 영수증 불일치는 시험 실패다. 오류 후 자동 재전송이나 다른 작성 경로로 fallback하지 않는다.

## 구현

- 새 `scripts/scoped-native-write-admission.mjs`는 임시 MCP 설정으로 공개 SB 쓰기 도구만 허용하고 실제 tool_use의 전체 인수를 원래 요청과 대조한다. 자격증명 값은 prompt에 넣지 않는다. 새 승인·검증·기억 저장 로직을 만들지 않는다.
- 기존 Python admission을 선택적으로 실제 native 클라이언트로 실행한다. 일반 모드는 기존 자비스 transport를 유지한다.
- `SB_NATIVE_SCOPED_WRITE=claude`는 `--mcp --cli`와 함께 사용해야 한다. 다른 값·불완전 옵션3가지는 fixture 생성 전에 거절하는 것을 확인했다.
- Python AST2개, JS구문3개, diff 검사 통과. 제품 코드 변경은 없으므로 이전40개 검사나 SB전체1,367개를 이번 실행 수로 합산하지 않는다. 최종 native 실행 후 추가한 옵션 거부 검사3개와 결과 한계 문구 정리는 모델을 재호출하지 않고 확인했다.

## 재실행

기존 CLI 로그인과 모델 사용량이 필요하다. JARVIS 작업공간에서 검증한 격리 빌드를 지정한다.

```bash
cd /home/jm/orca/projects/Orca-JARVIS
SB_NATIVE_SCOPED_WRITE=claude SB_PHONE_NATIVE_ACCEPTANCE=claude TMPDIR=/var/tmp node /home/jm/orca/projects/second-brain-app/scripts/scoped-provider-https-acceptance.mjs /absolute/isolated-jarvis-build --cli --mcp --readback
```

쓰기 모델 호출은 정상 시나리오에서만 사용한다. 철회·만료3개는 기존 실제 transport/HTTPS/CLI 경계 검사를 유지한다. 임시 MCP 설정·gateway·provider 자료를 사용하고 운영 설정과 서비스를 변경하지 않는다. no-session-persistence 옵션을 사용했지만 native 전역 캐시와 모든 보존 사본의 삭제 증거까지 확보한 것은 아니다.

## 보류와 남은 목표

- **보류:** 자유 모델 주장에 검증된 작업 권한을 붙이는 방식은 도입하지 않았다. 실제 업무 결과의 기존 verifier/원작업 근거가 필요하다.
- **미검증:** 작성·읽기는 서로 다른 실행과 agent지만 둘 다 Claude Code2.1.261이다. 다른 종류 클라이언트 Codex의 이전 사용량 제한은 이번에 재시도하지 않았다.
- **미완료:** 실제 운영 세션 자격증명 공급·교체, release/DB 전환, 운영 사용자 자료, 전체 삭제·복원·native 보존, 자동 수집·주입, 검색/GUI 품질과 전체 M1–M14는 유지한다.

이전 보고서의 “native A 작성 미실행”은 이번의 **검토된 요청 제출** 범위에서 갱신한다. 모델이 새 업무를 수행해 그 결과를 자동 검증하고 저장하는 전체 인수나 운영 완료를 뜻하지 않는다.
