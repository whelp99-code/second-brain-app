# v4 파일 발행과 수락 원장 확정 연결

2026-09-09. 이전 publisher 구현·실제 crash 복구·커밋은 진전이었다. 이번 단계는 내부 v4 수락 조합을 구현했다.

## 구현

`accept_scoped_request`는 현재 시각의 v4 codec 검증→필수 authority callback→명시적 v4 RequestStore/replay→파일 발행→authority 재검사와 현재 시각 검증→파일 재검증→원장 확정을 연결한다. callback은 정확히 True를 반환해야 하며 None/문자열/숫자는 거부한다. 초기 권한 거부 시 디렉터리/DB를 만들지 않는다. 발행 중 만료·시각 역행·권한 철회는 요청 행 생성 없이 거부한다.

수락 결과에는 provider·request/idempotency·scope digest·최초 accepted_at·inbox path·file digest가 결합된다. 재시도는 저장된 identity 전체를 비교하고 기존 result JSON을 재계산해 검증한다. 파일만 남은 중단은 기존 최초 bytes/시각을 채택해 원장에 기록하며, 이미 확정된 요청은 최초 수락을 replay한다. processing으로 이동한 요청의 pending 파일을 재생성하지 않는다. accepted/pending은 실행 완료가 아니다.

최종 authority callback이 파일을 바꾼 경우에도 commit 전에 private-file/inode/link/bytes 검증으로 거부한다. 폴더 잠금·발행·원장 replay는 기존 코드만 재사용한다. 새 signing/approval 엔진을 만들지 않았다.

## 검증

- 최종 admission/publication/journal/기존 write/walking skeleton **45 passed / 3.64초**. 이후 import 순서만 정리하고 전체 SB/helper Ruff와 diff 검사 통과.
- 초기 권한 거부/비boolean 허용값 거부, 발행 뒤 철회·만료·시각 역행·발행 오류 시 row0, orphan 재시도 원본 보존, processing 요청 replay, 마지막 권한 검사 중 파일 변조 시 row0을 확인했다.
- 실제 Python 프로세스4개. 발행 fsync 직후 exit73: row0→재시도 row1/replayed=false. 원장 확정 직후 응답 전 exit74: row1→재시도 row1/replayed=true. 두 경우 원문 bytes와 최초 시각 보존, 최종 state=pending.
- [실행 JSON](SCOPED-REQUEST-ACCEPTANCE-2026-09-09.json), `scripts/scoped-request-acceptance-crash.py`. 고정된 fixture authority callback과 합성 v4/임시 DB를 사용했으며 운영 인증이나 MCP 인수 증거는 아니다. 임시 자료를 정리했다.

## 보류·다음 완료 조건

authority callback은 내부 경계이며 아직 실제 검증 구현이 연결되지 않았다. 실제 authenticated transport·현재 policy·소비된 scope review 증거를 검증하는 구현이 필수다. 이번 fixture의 True callback을 제품 MCP에 연결하면 안 된다. 공개 MCP 수락 표면에는 노출하지 않았다. 원장 확정과 외부 정책 상태의 원자성까지 이번 검사로 보증하지 않는다.

다음은 자비스 범위 검토 단일 소비/outbox, provider의 구체적 수락 권한 검증, v4 실행기와 source_access 전달, 완료 영수증 및 인증된 다른 agent의 새 세션 회수다. 이 조건 전에는 운영 활성화·전체 범위 쓰기 완료를 선언하지 않는다. 전체 M1~M14 목표를 유지한다. 이번 전체 Python/Vitest·실제 모델·운영 서비스 인수는 재실행하지 않았다.
