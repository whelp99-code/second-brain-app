# 자비스 인증 경로의 실제 클라이언트 MCP 읽기

JARVIS `70d0428`은 기존 HTTPS context API를 호출하는 stdio MCP 연결부를 추가했다. 세컨드브레인 정본·기존 gateway 로그인/범위 검사·CLI/provider MCP를 재사용한다. [제품 사용·설정 문서](../Orca-JARVIS/docs/phone-memory-client-mcp-2026-09-09.md), [검증 결과](AUTHENTICATED-CLIENT-MCP-2026-09-09.json).

## 구현과 결함 수정

- `jarvis_memory_context` 하나를 제공하며 모델에게 query/limit/max_bytes만 받는다. 고정된 비공개 로컬 파일에서 HTTPS origin·현재 cookie/CSRF·선택 CA를 매 호출 읽는다. 로그인·갱신·별도 기억 저장·자동 재시도는 하지 않는다.
- 기존 파일 안전 검사, HTTPS 인증서 검증,20초 제한·취소·전체 응답 크기 제한을 적용한다. 응답의 query digest와 요청, 본문 canonical digest/bytes, 참고용·비신뢰 표식을 확인한다.
- 최초 실제 HTTPS 검사15개 중2개가 실패했다. 다른 질문의 응답 수락과 JSON escape로 표현한 토큰 노출을 재현한 뒤 요청 결합 및 해석 후 토큰 검사를 추가했다.
- MCP 프로토콜은 SDK1.30.0 고정 의존성으로 처리한다. 새 기억 서버/DB나 네 OSS 전체 설치를 추가한 것이 아니다.

## 실제 실행 증거와 한계

| 경로 | 최종 결과 | 한계 |
|---|---|---|
| 별도 SDK stdio 클라이언트2개→TLS→gateway→CLI→SB MCP | 각각2records, 원문·버전·출처 배열 일치 | 같은 설정 agent와 로그인으로 읽기 재시작 검사 |
| Claude Code2.1.261→새 MCP 연결부→같은 경로 | 실제 tool_use/tool_result1쌍,2records 일치, result success | 실제 모델 읽기이며 쓰기/자동 주입 시험은 아님 |
| Codex 실제 CLI | 사용량 제한으로 turn.failed, 도구 호출0 | **이번 검증 보류**. 연결 성공이나 지원 완료로 표시하지 않음 |
| 기존 다른 agent의 제한 범위 검사 | 허용 agent2records, 제한 peer0records | 격리 정책/자료로 검증 |
| 정책 철회·세션 만료 | 각각403·401 | fixture 시계, 실제 운영 세션 수명 검증과 구분 |

최종 실제 시험의 HTTPS 호출은3회(독립 SDK2+Claude1)다. 두 모델 전체 시험은 Codex quota 때문에 실패했으며 그 후 Claude 전용 모드로 최종 성공을 확인했다. 첫 Claude 시도에서는 가변 길이 `--allowedTools` 인수가 prompt까지 삼켜 입력 없음으로 실패했다. 인수 종료 표시와 stdin 종료를 명시해 해결했으며 제품 오류로 분류하지 않았다.

관련 고유 **40개/3파일 통과(2.56초)**: 신규HTTPS/MCP15, 기존context CLI9, 오류 분류16. 격리 TypeScript emit·ESLint·세 인수 스크립트 구문·diff 검사 통과. SB 제품 소스는 변경하지 않아 전체1,367/2skip 검사를 반복하지 않았다.

인증 전달자, source, policy, clock, DB는 임시 시험 구성이다. TLS 시험 전달자는 기존 테스트 gateway가 기대하는 Host/Origin/Tailnet identity로 매핑한다. 실제 native 클라이언트가 이 헤더를 직접 위조하는 경로가 아니며 운영 Tailnet 배포 검증도 아니다. 임시 gateway·TLS·MCP 자식은 종료하고 자격증명 디렉터리는 제거한다. native 클라이언트 전역 캐시/모든 보존 사본까지 삭제했다는 증거는 없다.

## 재실행

작업공간에서 검증한 JARVIS 격리 빌드 절대 경로를 제공한다. 기본 모드는 모델 사용 없이 독립 stdio2개를 검증한다.

```bash
TMPDIR=/var/tmp .venv/bin/python scripts/scoped-mcp-acceptance.py /absolute/isolated-jarvis-build
SB_PHONE_NATIVE_ACCEPTANCE=claude TMPDIR=/var/tmp .venv/bin/python scripts/scoped-mcp-acceptance.py /absolute/isolated-jarvis-build
SB_PHONE_NATIVE_ACCEPTANCE=1 TMPDIR=/var/tmp .venv/bin/python scripts/scoped-mcp-acceptance.py /absolute/isolated-jarvis-build
```

`claude`는 실제 Claude만, `1`은 Claude와 Codex 모두를 요구한다. native 시험은 기존 로그인·모델 사용량이 필요하며 임시 MCP 설정만 사용한다. native 실패를 성공으로 바꾸는 fallback은 없다.

## 다음 완료 조건

실제 A의 scoped 쓰기→완료 영수증→B 새 로그인 회수는 아직 미완료다. 이 읽기 연결부를 해당 시나리오의 소비자에 붙이고 동일 task/request/record 계보, 재시작, 철회와 삭제 후 재유입 억제를 검증한다. Codex는 사용량 제한 해소 후 같은 실제 경로를 재실행한다. 운영 자격증명 공급·교체, 릴리스/DB 전환, native 세션 삭제·복원, 자동 주입 및 M1–M14 전체 인수는 유지한다. 운영 배포·재시작·설정/DB 변경·push는 하지 않았다.
