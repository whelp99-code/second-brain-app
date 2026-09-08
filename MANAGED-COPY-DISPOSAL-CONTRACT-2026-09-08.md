# 관리형 압축 사본 처분과 재시작 체크포인트

기존 단일 generation writer와 request journal을 재사용하는 결함 수정이다. 새 외부 계약·
DB·키·승인 절차를 추가하지 않는다. SB 정본/JARVIS 실행 및 OSS 선별 흡수 방향을 유지한다.

1. 백업은 원시 바이트와 제한된 gzip/tar/Git loose object의 해제 내용을 함께 검사한다.
   디스크에 해제하지 않는다. 불완전·미지원·예산 초과 형식은 검사 오류이며 일치 0 증거가 아니다.
2. 정정·삭제·취소는 원본 세대가 남아 있는 동안 백업과 관련 export를 먼저 처분한다.
   generation 전환 직전 writer 안에서 실행하고 현재 tombstone을 다시 검사한다.
3. 사본 처분 후 원장에 operation/요청 digest/결과 generation/관리 root와 파일 내용 목록의
   digest를 저장한다. 원문과 검색 needle은 저장하지 않는다. 기존 FULL 동기 SQLite를 사용한다.
4. 원본이 있으면 재시작마다 다시 검사·처분한다. 원본이 없어졌으면 저장된 체크포인트와
   현재 내용 목록이 일치해야 진행한다. 증거 누락·파일 변경은 복구 보류이며 빈 needle로
   처분 성공을 합성하지 않는다. 후속 세대 이후 재생은 과거 generation 활성화의 증거만 반환한다.
5. 이 체크포인트는 내부 복구 증거다. 전체 native 보존면 처분, 취소의 최종 서명 영수증,
   MCP/JARVIS cursor 완료 및 자동 취소 route의 인수 조건을 대신하지 않는다.

검증: 실제 provider tar.gz 생성, 정정·삭제·취소의 export와 백업 제거, pointer 이후 중단 복구,
증거 누락/사본 변경 거부, 압축 오류·예산·내부 Git 내용, 전체 기존 회귀. 운영 데이터는 사용하지 않는다.

## 후속: 남는 정상 archive의 manifest 검증

삭제 대상이 없는 canonical backup도 정정 후 남길 수 있어야 한다. 기존 디렉터리 manifest
형식에 더해 create_backup의 archive+checksum 형식을 검증한다. 내부 manifest의 경로·크기·
해시와 실제 전체 regular member 집합을 대조하며 해제 파일을 디스크에 만들지 않는다.
checksum 단독 또는 문법만 맞는 manifest를 복원 가능성의 증거로 인정하지 않는다.
이 검증은 파일 집합 무결성이며 최신 tombstone/권한을 적용하는 restore 권한 검사를 대체하지 않는다.
