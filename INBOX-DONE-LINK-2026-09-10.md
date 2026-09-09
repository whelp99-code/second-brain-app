# 받은편지함 처리 완료 경로의 링크 이탈 수정

실제 회귀에서 inbox/.done을 외부 디렉터리 symlink로 지정한 뒤 acknowledge를 실행하자 원문이 외부로 이동했다. 수정 전 테스트는 원래 inbox 파일이 사라져 실패했다.

_move_done은 root와 source/destination의 각 중간 디렉터리를 O_DIRECTORY|O_NOFOLLOW로 열고 descriptor-relative mkdir/open/replace를 사용한다. symlink 디렉터리는 거절하고 원문을 유지한다. 절대경로/상위경로 구성도 거절하며 모든 descriptor를 finally에서 닫는다. registry·connector 경계 변경 없음.

수정 후 실제 symlink 회귀 및 기존 nested done이동/수집·pending inbox/walking skeleton 포함21passed/4.10초. Ruff전체/diff통과, 변경모듈타입0오류0경고. 사용자 데이터나 운영 vault를 사용하지 않았다.

한계: 이미 열린 디렉터리 자체의 외부 이동, 원문검증 이후 source basename교체, 완료 목적지의 기존파일 덮어쓰기 정책은 별도 경합/보존 문제다. 이번 수정은 열린 경로의 symlink 추적을 차단하며 전체원자적처분 증거로 확대하지 않는다. 이전의 bounded읽기 개선과 함께 적용되며 전체M1–M14/실사용·운영 목표유지.
