# 접수된 취소의 실제 억제 세대 처리

기존 cancellation journal 접수 다음 단계. 별도 MCP/CLI route는 아직 노출하지 않는다.
이미 접수된 의향을 accepted_at에서 재검증하고 현재 허용된 취소 키 목록도 요구한다.
원래 요청이 만료되었더라도 접수 당시 유효했던 의향의 실행은 재개할 수 있다.

내부 실행은 같은 pending flock을 완료까지 유지한다. 기존 generation writer 및 journal과
잠금 순서를 pending → generation → 짧은 journal transaction으로 유지한다. 파일 접수와
실행이 경합하는 것을 막는 보수적인 초기 방식이며 처리 중 다른 접수의 지연을 감수한다.
공개 route를 연결하기 전에 긴 처리의 대기/만료 정책을 함께 인수한다.

새로 서명된 일반 V2 request를 만들거나 정정 본문을 복원하지 않는다. ErasureEngine의
기존 삭제 처리에 대상·이력·요청 식별자를 전달하는 내부 구조를 추출하여 재사용한다.
취소 처분은 suppression이며 기존 대상만 제거하고 원래 정정 payload는 적용하지 않는다.
동일 source/content/citation/subject의 재수집 차단도 기존 reingress gate로 지속한다.

현재 generation의 id/manifest/head/tree와 커밋된 target blob/span을 검사한 다음 변경한다.
대상 불일치는 새 세대 생성 전에 거부한다. 기존 GenerationMutationService가 단일 writer로
staging/인덱스/봉인/포인터 전환/이전 세대 정리를 수행한다. 기존 request journal에
intent→sealed generation의 연결을 기록하여 포인터 전환 직후 중단을 재개한다.

결과는 generation_active이며 provider 전체 물리 삭제나 서명된 최종 영수증이 아니다.
backup/export/native 처분, 활성 권한 정책의 실제 구성, 외부 상태 조회/결과 계약과 자비스
cursor settlement는 후속 필수다. 이 중간 결과로 자비스 lane을 자동 건너뛰지 않는다.
