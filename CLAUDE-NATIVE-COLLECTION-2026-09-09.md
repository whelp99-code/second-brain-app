# Claude 원본 세션 수집 누락 수정

기존 claude-sessions connector는 정규화 export의 message/tool_use/tool_result를 처리했지만 실제 Claude Code JSONL의 user/assistant 레코드를 무시했다. 기본 root가 ~/.claude/projects여도 원본 가시 대화가 수집되지 않는 결함이었다.

sb/connectors/claude_native.py에서 원본 형식을 처리하고 기존 sessions_claude의 해당 두 type에만 연결했다. 정규화 export 지원은 유지한다. 소스 본문은 claude-native-visible-v1 JSON으로 세션 ID, 메시지 UUID, role, 블록 순번, type, 가시 텍스트 또는 도구 정보를 보존한다. source_uri에도 세션/UUID/블록 위치를 결합한다. 필수 출처가 없으면 lineage로 건너뛰며 임의 ID를 만들지 않는다.

- user 문자열 및 user/assistant text 블록을 수집한다.
- tool_use ID/name/input, tool_result의 같은 tool_use_id/가시 결과/is_error를 보존한다. is_error가 없으면 null이며 성공으로 추정하지 않는다.
- thinking/redacted thinking, 이미지·바이너리, 알 수 없는 확장 블록과 isMeta 메시지는 기억 본문으로 전달하지 않는다.
- 원본 role 불일치나 잘못된 도구 필드 형식은 invalid-format으로 처리한다.

## 검증

| 검증 경로 | 결과 |
|---|---|
| 수정 전 회귀 | 4개 실패: 원본 메시지·도구 오류·출처 누락이 모두 조용히 무시됨 |
| 수정 후 관련 검사 | 24통과, 기존 export 및 부분 JSONL 재시작 검사 포함 |
| 전체 pytest | 1,362 passed / 2 skipped / 246.29초, 선택 embeddings 제외 |
| 정적 검사 | 전체 Ruff, 새/변경 모듈 basedpyright 0 errors/0 warnings |
| 기존 실제 native 파일 표본 | 3개 파일 각 최대100줄, text13/tool_use42/tool_result41 =96블록 수집, skip0·재조회0 |
| 새 실제 Claude Code 실행 | 2.1.261, safe-mode·도구 없음·임시 cwd·새 세션. 3.55초/exit0, 원본 로그의 사용자/답변2블록 수집·동일 세션 출처·재조회0 |

표본 원문은0700 임시 디렉터리의0600 파일에서 실제 connector로 처리한 뒤 제거했다. 출력에는 블록 종류·개수만 기록했다. 새 실제 모델 실행은 합성 표지를 그대로 답하는 요청이며 숨긴 정답 회수나 A→B 공유를 검증한 것은 아니다. 생성한 해당 시험 세션 JSONL도 제거했다. 다른 native 캐시·백업·전역 메타데이터의 완전한 삭제를 증명한 것은 아니다. [검증 JSON](CLAUDE-NATIVE-COLLECTION-2026-09-09.json).

## 남은 연결 및 적용 범위

도구 ID 보존은 원문 상관관계의 근거이며 모든 호출/결과 쌍이 완전하게 수집됐거나 외부 효과가 성공했다는 검증이 아니다. 이 JSON을 자비스의 완료 영수증으로 사용하지 않는다. 메시지의 세션/역할 라벨도 접근 권한을 발급하지 않는다.

운영에 이미 저장된 cursor 이전의 무시된 레코드는 자동으로 재수집하지 않는다. 배포 후 과거 수집 범위·삭제 억제·중복을 확인한 명시적 복구 절차가 필요하다. 운영 서비스·설정·vault·원장에는 변경하지 않았다. 새 수집 코드는 운영 미배포다.

실제 자비스 인증 A→B 공유, 클라이언트별 수집·주입 표, native 보존/삭제, OMO/GJC 부분 기록, 검색·GUI·복구와 전체 M1–M14 인수는 유지한다. 관련24개를 전체1,362개와 합산하지 않는다.
