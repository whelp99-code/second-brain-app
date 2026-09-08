# 자비스 인계 재대조와 독립 프로세스 제출 검증

기준: 2026-09-09. SB 검증 코드 `a3da3b4`, JARVIS 기존 제품 `121d06b`.

판정: 저장·검색·범위 검사·문맥 공급의 일부 경로는 검증됐다. 자비스와 여러 에이전트의 메인 기억 장소로 전체 운영 인수한 상태는 아니다. 이 보고서는 인계 내용을 기존 수정에 병합하며 이전 미완료 조건을 유지한다.

## 인계와 기존 구현의 대조

[인계 원문](../Orca-JARVIS/docs/second-brain-oss-absorption-handoff-2026-09-07.md)의 확정 방향을 재확인했다. 세컨드브레인은 개인·업무 기억 정본, 자비스는 실행·결과 검증, dev-wiki/Git은 개발 결정 원문이다. 아래 OSS 항목은 인계서의 고정 커밋 조사에 근거하며 최신 upstream 재조사나 외부 코드 복사는 수행하지 않았다.

| 대상 | 분류 | 기존 기능과 적용 방법 | 남은 증거 |
|---|---|---|---|
| LightRAG | 기존 기능 개선 | `sb/search.py`, `sb/hybrid_search.py`, `sb/sealed_search.py`의 근거 검색·삭제 일관성 재사용 | 실제 한글 질문의 근거 회수율·낡은 결정·지연 측정. 그래프는 효과 확인 후 채택 |
| TencentDB-Agent-Memory | 연결·활성화 부족 | 기존 MCP 계약과 원본/페이지 범위 검사, JARVIS scoped client를 공통 접점으로 사용 | 실제 인증 진입점과 쓰기·복구까지 같은 범위 적용 |
| code-brain | 기존 기능 재사용·연결 개선 | 기존 reference reader의 문맥 예산·근거·제출 기록 사용 | 실제 클라이언트 세션 식별과 전달 영수증·재개 검증 |
| memory-bank | 계보·수명주기 개선 | 기존 source/page/record와 정정·삭제 이력 재사용 | 검증된 작업 결과 연결, 에이전트별 실제 수집/주입 및 삭제 전파 |

네 제품 설치나 별도 기억 DB는 필요 작업으로 추가하지 않았다. 전체 수정·개선·고도화 목록은 [통합 분석 M1~M14](SHARED-MEMORY-CONSOLIDATED-REVIEW-2026-09-09.md)에 유지한다.

## 이번 구현과 실행 결과

기존 인수는 같은 Node 프로세스에서 새 reader를 생성했다. 이번에는 별도 Node 프로세스가 같은 시험용 SQLite 원장을 새 연결로 열고, 제품 factory와 자체 MCP 전송기를 구성하여 실제 Python MCP에서 기억 2개를 다시 조회했다. 동일 native session/epoch로 제출하면 `MEMORY_REFERENCE_ALREADY_SUBMITTED`로 거부됐으며 전달 콜백은 0회였다.

- 부모의 최초 전달: 2 records / 4,412 bytes. 인증 범위를 포함한 원장 binding HMAC 검사 통과.
- 별도 프로세스 재조회: 2 records. 중복 전달 거부, 콜백 0회.
- 기존 v1/v2 조회·검색, 전후 세대 일치, 응답 변조·빈 결과 세대 대체·쿠키 누락·응답 후 정책 철회 거부도 같은 인수 실행에서 통과.
- `uv run ruff check sb tests`, 두 변경 JavaScript의 `node --check`, `git diff --check` 통과.
- 이번에는 전체 pytest나 전체 JARVIS 테스트를 재실행하지 않았다. 과거 전체 통과 수를 현재 수치로 재표기하지 않는다.

재현 명령:

```bash
TMPDIR=/var/tmp uv run python scripts/scoped-mcp-acceptance.py "$(cat /var/tmp/cancellation-material-build-path.txt)"
```

해당 marker는 이 머신의 격리 JARVIS 빌드를 가리킨다. 다른 환경에서는 검증한 JARVIS TypeScript 빌드 절대 경로를 인자로 전달한다. 실제 결과는 [보존한 JSON](SCOPED-PROCESS-REOPEN-2026-09-09.json), 원 실행 파일은 `/var/tmp/page-access-acceptance-k43ye48g/scoped-mcp-result.json`이다.

제한: 자식 프로세스의 인증 정보는 부모가 전달한 시험용 identity snapshot이다. 실제 HTTP 인증 전달을 구현한 것이 아니다. 합성 원본·fake compiler·시험용 키/owner·고정 시각·fixture native session/epoch를 사용했다. 부모 프로세스 종료/장애 복구나 실제 모델 로그 삭제의 증거도 아니다. 자식은 자신의 전송기와 DB 연결만 닫으며 시험 데이터 제거는 부모가 담당한다. 운영 서비스·DB·설정은 변경하지 않았다.

## 우선순위와 구체적인 완료 조건

| 순서 | 관점 | 필요한 작업 | 완료 조건 |
|---|---|---|---|
| 1 | 연결 개선 P0 | 기존 phone 인증에서 실제 JARVIS 기억 진입점까지 신뢰된 세션 전달 및 새 세션 정책 배정 | 실제 로그인 조회 성공, 다른 프로젝트/만료/철회 거부. 공통 CSRF를 사용자 인증으로 해석하지 않음 |
| 2 | 기능 완성 P0 | scoped 쓰기·처리 상태·대상 해석 연결 | 조회→작업 결과 검증→저장 요청→영수증→새 세션 재사용을 동일 요청 계보로 입증 |
| 3 | 무결성 수정 P0 | 정책 rollback·삭제 high-water·다중 writer/경로 교체 보호 | 옛 정책 복원·동시 실행·중단에서도 불허 기억/중복 효과가 되살아나지 않음 |
| 4 | 계보·세션 개선 P0 | task→검증 결과→candidate→record, 실제 모델 세션 보존·삭제 연결 | 실패 실행이 성공 기억이 되지 않으며 정정/삭제가 재개·요약·로그·지원 백업까지 반영 |
| 5 | 공통 접근 P0/P1 | 읽기·쓰기·hybrid·원문·복구의 범위 일치, 클라이언트별 지원표 | 서로 다른 실제 에이전트의 상호 회수 및 조회/쓰기/수집/주입을 각각 확인 |
| 6 | 품질·운영 개선 P1 | 한글 질문 평가, 문맥 중복/예산, 실패·영수증 화면, 복원 훈련 | 근거 회수/no_data/지연·사용량과 RPO/RTO를 실측 |
| 7 | 선택 고도화 P2 | 관계 확장과 영향받은 파생 인덱스만 갱신 | 동일 평가 세트에서 개선이 입증되고 정정·삭제·접근 제한 유지 |

이번 독립 프로세스 검증은 제출 원장 재사용의 증거를 보강했다. 1~6의 전체 운영 완료 조건을 대신하지 않는다.
