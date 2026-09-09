# 설정 원본 누락의 조용한 생략 수정

_select_adapters는 설정의 source ID에 대응하는 adapter가 없으면 continue로 넘겼다. 암묵적 배치를 설정 원본으로 제한한 후에도 잘못된 ID가 빈 작업 또는 부분 수집으로 보일 수 있었다. 회귀에서 예외가 발생하지 않는 문제를 재현했다.

알 수 없는 설정 원본을 SOURCE_NOT_FOUND로 거부한다. 모든 설정 선택은 scan 전에 수행하므로 정상 원본과 잘못된 원본을 섞었을 때 정상 원본만 먼저 소비하지 않는다. 명시적으로 다른 원본만 선택하더라도 전체 설정에 미지원 ID가 있으면 실패한다. 잘못된 설정을 먼저 고치도록 하는 동작이다.

검증: 관련 configured selection/CLI/run_all/runtime reliability **68 passed / 8.82초**, Ruff/diff 통과. 별도 임시 저장소에서 inbox+미지원 adapter를 설정하고 실제 run_ingest를 실행했다. failed/exit1/SOURCE_NOT_FOUND, source_item0, inbox 원본 보존을 확인했다. [실행 증거](INVALID-CONFIGURED-SOURCE-2026-09-10.json).

## 관리형 UNVERIFIED 판정 대조와 보류

앞선 관리형 검색 결과의 UNKNOWN/UNVERIFIED는 `_register_compiled`가 .staging root에서 외부 registry 쓰기를 생략하는 코드와 일치한다. 해당 임시 저장소의 명시 registry.sqlite는 존재하지 않았다. 파일을 읽기 전용으로 열려던 첫 확인도 파일 부재로 실패했으며, 이를 빈 등록 테이블을 읽었다고 표현하지 않는다.

staging에서 외부 레지스트리로 자동 APPROVED를 기록하는 우회는 적용하지 않았다. 세대 활성화 전후의 실패·복구·정정·삭제와 같은 원자성 경계 안에서 상태를 연결해야 한다. 다음 단계는 봉인 세대 상태 또는 공개 이후 복구 가능한 projection을 기존 정책과 대조하는 것이다. 단순히 UI 표시를 VERIFIED로 바꾸지 않는다. 이번 변경은 원본 선택 오류만 수정하며 전체 승인 상태 연결 완료는 아니다.

운영 데이터·서비스 변경 없음. 최신 설치 반영·실제 업무 공유·운영 및 M1–M14는 남는다.
