# 취소 대상의 세대 고정을 접수에 결합

직전 실행기는 접수 후 실제 generation/target을 검사했다. 오래되거나 변조된 대상의 취소가
먼저 영구 원장과 tombstone replica에 들어가 정상 조회·후속 처리를 막을 수 있는 공백을 닫는다.

공개 내부 접수 함수는 실제 GenerationStore를 필수 입력으로 받고 request root와 provider가
같은지 검사한다. 잠금 순서는 pending-directory flock → 기존 generation writer/exclusive →
journal BEGIN IMMEDIATE이다. DB transaction을 잡은 채 generation writer를 기다리지 않는다.
기존 writer가 이미 진행 중이면 기다린 뒤 결과 세대를 검사한다. 취소가 먼저 세대를 고정하면
대상 검사와 journal commit 사이에 다른 writer가 끼어들지 못한다.

새 취소에만 실제 활성 generation과 원 요청 target의 provider/id/manifest/head/tree,
커밋 blob/content/span을 검사한다. 활성 세대의 tombstone 위치도 취소 delta의 직전 위치와
같아야 한다. 원장 접수 재생은 대상 검사 없이 기존 canonical bytes 동일성으로 판단한다.
이미 처리된 취소는 원본 대상이 삭제됐다는 이유로 접수 재생이 실패하면 안 된다.

파일 검사와 대상 읽기 이후 현재 시각·현재 키를 다시 확인해 기다리는 동안 만료된 의향이
접수되지 않게 한다. 서명·대상·세대·직전 위치 중 하나라도 맞지 않으면 별칭/취소/tombstone
데이터를 추가하지 않는다. 기존 원장 단위 테스트는 대상 바인딩을 명시적으로 모의하며,
실제 바인딩·잠금 경합은 별도의 실제 generation 및 프로세스 테스트가 검증한다.

접수 결합도 최종 삭제 영수증은 아니다. backup/export/native 처분, 버전 결과·상태 조회와
자비스 cursor 완료 계약 전까지 자동 취소 route와 lane 건너뛰기를 보류한다.

추가 대조에서 기존 backup_runtime/verify_runtime_backup이 generation → pending → journal
순서임을 확인했다. 새 취소 경로와 경합하면 서로 기다릴 수 있다. 실제 pending 잠금 대기 중
generation mutex 획득을 시험해 두 경로 모두 충돌을 재현했다. 백업도 pending → generation →
journal로 통일하며 pending 동결과 DB transaction을 분리한다. snapshot의 원자성과 SQLite
WAL을 포함하는 backup API 사용은 유지한다.
