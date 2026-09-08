# 자비스 scoped 준비값의 세컨드브레인 검증·분류 연결

2026-09-09. 이전 goal 단계는 제품 수정·49개 관련 검사·두 리포 커밋으로 진전했다. 이번 단계는 M2의 범위 쓰기 계약에 필요한 provider 측 데이터 검증을 구현했다. 전체 완성 목표는 유지한다.

`sb/scoped_write_preparation.py`는 실제 JARVIS `prepareMemoryScopedWriteFromDispatch` 결과의 정확한 필드, 버전, 쓰기 미승인 표시, scoped identity/idempotency, 본문·제목 digest, 전체 preparation digest, 만료와 payload 정책을 확인한다. 검증된 identity를 기존 `SourceAccess`로 변환하고 frozen 객체·canonical bytes로 반환한다. 입력 객체 변경이 반환된 프로젝트 목록에 반영되지 않는다.

이 값은 아직 쓰기 요청이나 권한 증거가 아니다. 호출자가 해시를 다시 계산할 수 있으므로 codec 통과만으로 현재 정책·원본 권한·검토 서명 검증을 대체해서는 안 된다. MCP에 노출하거나 ledger에 기록하지 않았다. 기존 v1/v3 계약도 변경하지 않았다. 범위 검토를 기존 confirmation으로 위장하는 방식과 read claim을 write 권한으로 사용하는 방식은 계속 보류한다.

## 실 실행 검증

- 기존 격리 TypeScript build에서 실제 v3 classify CLI→private spool→서명된 범위 검토→준비 API 실행. helper에 `--include-preparation` 옵션을 추가했다.
- Python 독립 프로세스가 생성 결과를 읽어 identity와 preparation digest를 검증했다. 본문 **51 UTF-8 bytes**, 한국어·CRLF 보존, 프로젝트 `project:shared-memory` 일치. 이 과정에서 provider 쓰기는 실행하지 않았다.
- 해당 JARVIS 출력은 `tests/fixtures/scoped_write_preparation_v1.json`에 합성 데이터 fixture로 보존했다. 코드·라이선스 외부 복사는 없다.
- 초기 helper 실행은 SB cwd에서 JARVIS fixture 정책 파일을 찾지 못해 실패했다. 명시된 JARVIS cwd로 재실행하여 성공했다. 제품 검증을 우회하지 않았다.
- codec/identity 관련 **23 passed**. 제목·본문·프로젝트·키·만료·허가 표시 변경, 추가 필드와 모호한 시각을 거부한다. 초기 lint의 의도적 naive datetime 작성 방식은 명시적 timezone 제거로 수정했다. 최종 전체 Ruff 통과. 최종 재실행은 walking skeleton 통합 gate를 포함해 **25 passed / 2.94초**다.

## 다음 구현 단위

1. 현재 프로젝트 정책과 원본 권한을 검증하는 자비스 enqueue 경계에 scoped request를 연결하고 검토 영수증을 한 번만 소비한다.
2. 양쪽 버전 계약에 scope identity·payload·영수증을 결합한다. 기존 저장된 계약 hash와 migration은 변경하지 않는다.
3. 요청별 불변 `SourceAccess`를 수락 원장→원본→봉인 record 계보로 전파한다.
4. 실제 MCP 저장→완료 영수증→다른 agent 새 세션 회수와 불허 프로젝트 거부를 검증한 후 쓰기 capabilities를 활성화한다.

준비 codec은 위 1~4 완료의 대체물이 아니다. 현재 운영 서비스 정상 여부나 실제 모델 세션 지원도 이번 검사로 확대 판단하지 않는다.
