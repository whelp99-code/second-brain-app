# 공개 scoped 쓰기 → 자비스 완료 → 새 agent 로그인 → 실제 Claude 회수

[인증 MCP 연결부](AUTHENTICATED-CLIENT-MCP-2026-09-09.md)의 읽기 시험을 기존 실제 HTTPS 쓰기 시험과 같은 데이터·요청으로 연결했다. 자비스 제품 기준은 `70d0428`이며 이번에는 제품 코드 대신 재현 가능한 통합 인수를 확장했다. [기계 판독 결과](SCOPED-WRITE-TO-NATIVE-READ-2026-09-09.json).

## 한 요청으로 검증한 흐름

1. 기존 자비스 fixture가 검증된 합성 작업 결과를 일반 classify/dispatch/scope review 경로로 준비한다. 원래 쓰기 agent는 `agent:fixture`다. 작업 증거·정책 결정은 시험 자료이며 실제 모델이 수행한 업무가 아니다.
2. 실제 공개 `sb_write_request` MCP→TLS→현재 gateway 로그인·정책 검증으로 수락한다. 일반 SB CLI `apply-requests --once`에서 같은 요청을 실행하여 provider `proved`가 된다.
3. 쓰기 프로세스 종료 후 같은 provider 저장소를 새 MCP 프로세스에서 연다. 별도 gateway의 새 로그인에 `agent:reader`를 배정한다. writer와 cookie가 다른 것을 확인하고 현재 reader 정책으로 접근한다.
4. 실제 `/api/v1/memory/reconcile`→일반 자비스 CLI→journal MCP→v5 현재 상태/기억 검증을 거쳐 원작업 `completed`, outbox `settled`로 원자 완료한다. 같은 요청을 다시 조회하면 replay이며 settlement1·dispatch attempt1·FK 오류0을 유지한다.
5. 그 후 context 검색으로2records를 회수한다. provider proof의 request ID/digest를 원래 dispatch와 비교하고 proof의 원문 SHA-256, 검색 record의 generation을 대조한다. 검색된 본문 조각이 실제 제출 본문에 포함되는지 확인한다.
6. 독립 stdio MCP 클라이언트2개와 실제 Claude Code2.1.261의 새 실행에서 같은2records를 회수한다. 실제 Claude tool_use/tool_result1쌍과 성공 result를 검사한다. reader 정책을 철회하면 같은 로그인으로403이 반환된다.

`source_ref` 표시값은 “Second Brain”이다. 이것만으로 원작업 계보를 판정하지 않고 원래 request/증명/세대/record 결합을 검사했다. 검색 query는 `결정`이며 Claude 프롬프트에는 반환될 원문 내용을 넣지 않았다. Claude는 회수자이며 이 시험의 작성자는 검증된 작업 입력을 공급하는 fixture다.

## 최종 결과

| 조건 | 수락/실행 결과 | 쓰기 권한 HTTPS 호출 | 전송 시도 | FK 오류 |
|---|---|---:|---:|---:|
| 정상 | proved→자비스 settled/completed→새 로그인·Claude 회수 | 5 | 1 | 0 |
| 수락 중 철회 | 수락 행 없이 denied | 2 | 1 | 0 |
| 실행 전 철회 | failed, 활성 세대 없음 | 3 | 1 | 0 |
| 실행 전 로그인 만료 | failed, 활성 세대 없음 | 3 | 1 | 0 |

정상 읽기의 별도 TLS 호출은3회(독립 SDK2+Claude1)다. 쓰기 권한 확인5회와 합산해 동일 종류의 호출인 것처럼 표시하지 않는다. 일반 HTTP context 조회·reconcile/replay는 위 TLS 호출 수에 포함하지 않았다.

모델 없는 전체4상태 인수와 실제 Claude를 포함한 최종 전체4상태 인수가 모두 exit0이다. JS3파일·Python AST 구문 및 diff 검사를 통과했다. SB/JARVIS 제품 소스 변경이 없어 제품 전체 테스트를 반복하지 않았다. 기존40개 단위·통합 검사는 직전 제품 단위의 기록이며 이번 실행 수로 합산하지 않는다.

## 재실행과 구성

JARVIS fixture가 리포의 고정 정책 파일을 읽으므로 **JARVIS 작업공간**에서 실행한다. 빌드는 격리된 출력 경로를 지정한다.

```bash
cd /home/jm/orca/projects/Orca-JARVIS
SB_PHONE_NATIVE_ACCEPTANCE=claude TMPDIR=/var/tmp node /home/jm/orca/projects/second-brain-app/scripts/scoped-provider-https-acceptance.mjs /absolute/isolated-jarvis-build --cli --mcp --readback
```

환경 변수를 생략하면 실제 모델 없이 독립 stdio2개를 검증한다. `SB_PHONE_NATIVE_ACCEPTANCE=1`은 Claude와 Codex 둘 다 요구하며 Codex의 앞선 계정 사용량 제한은 이번에 재시도하지 않았다. 실패를 성공으로 바꾸는 fallback은 없다.

- `scripts/scoped-provider-https-acceptance.py`: 실제 저장에 사용한 config와 proof로 새 read launcher/config를 구성한다. 새로 기억을 복제하거나 내부 수락으로 대체하지 않는다.
- `scripts/scoped-written-context-acceptance.mjs`: 같은 authority/provider, 새 reader 로그인, 실제 reconcile와 context, 증명/세대 대조를 연결한다.
- `scripts/phone-memory-client-acceptance.mjs`: query를 매개변수화해 기존 Cited 시험과 새 결정 검색을 같은 실제 MCP/native 검증기로 실행한다.

구현 중 재현 실패는 시험 구성의 상대 작업경로, Content-Type charset, issuer session 설정, 정책 method 정렬, preparation payload 경로 및 digest 용도 혼동이었다. 기존 검사 조건을 완화하지 않고 정의된 계약에 맞춰 수정했다. preparation의 domain-separated content digest와 proof의 원문 SHA-256을 같은 값으로 비교하면 안 된다. 최종 검사는 proof와 원문 bytes의 SHA-256을 비교한다.

## 유지하는 미완료 범위

이 시험은 실제 네트워크·프로세스·제품 계약을 연결하지만 운영 인수 완료는 아니다. 시계는 고정값이며 provider 실행일 뒤의 새 로그인 시각을 사용한다. 시간 변경은 대기나 운영 시계 조작 없이 fixture에만 적용한다. native 모델 A의 쓰기와 다른 종류 모델 B의 새 세션 회수, 운영 자격증명 공급·교체와 서비스 배포, 전체 native 로그/백업 삭제·복원, 자동 주입 및 M1–M14는 남는다. 합성 검증 결과를 실제 업무 성공 증거로 보고하지 않는다.

운영 DB·설정·서비스·기존 개인 vault는 변경하지 않았다. 자비스 제품 코드를 우회하는 새 기억 정책/DB/서버 기능을 만들지 않았으며 push하지 않았다.
