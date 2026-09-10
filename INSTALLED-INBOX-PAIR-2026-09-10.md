# 최신 수집 수정 설치물과 자비스 연동 인수

소스 `f0fec140aee0fbe14fcd9289e7461509144a6c7e`를 git archive로 추출하여 offline locked 릴리스를 준비했다. 릴리스 ID `78a5792d53a7cbdb1b4d4c50f58ca63cd97c77f1`, wheel SHA-256 `e58e53206cca84d417ab0845c30464c609e004e88fc00b241782bc719784ccab`.

설치 위치 `/var/tmp/sb-inbox-release-gicqbwxw/releases/78a5792d53a7cbdb1b4d4c50f58ca63cd97c77f1`. 준비 명령은 `python deploy/prepare-release.py <root> --offline`이다. 기존 미추적 파일이 있어 manifest의 working_tree_modified는 true이지만, archive는 명시한 커밋만 포함하며 해당 파일을 패키지에 넣지 않았다.

## 설치 검증

1. `check-release-integration.py`와 기존 격리 자비스 빌드 `/var/tmp/jarvis-current-pair-_mq15nmd/source/dist`: exit0. 실제 TLS/HTTP/CLI/MCP 공개 쓰기→provider proved→자비스 settled/control completed→새 로그인 조회 성공. 독립 stdio reader2개가 각 record2개 회수하고 reader 철회 후403. settlement/attempt 각1, FK 오류0. 접수 중 철회는 accepted row 없이 거부, 실행 전 철회/만료는 failed이며 active generation 없음.
2. 같은 설치물 `check-release-maintenance.py`: exit0. 살아 있는 workspace는 busy로 보존, worker SIGKILL(-9) 뒤 정리1개, 재실행 정리0개. 새 프로세스3회에서 유지 기억1개와 generation/body/ledger/high-water 동일 확인.
3. 같은 설치 Python을 `-I`로 실행하고 connector import가 설치 경로 아래임을 검사했다. 실제 CLI 별도 프로세스2회로 같은 이름에 서로 다른 문서를 수집하여 이전 이름의 원본 유지, 보관 원본2개·봉인 원장 source version2개 확인. exit0. `/var/tmp/sb-installed-inbox-qyza638d/result.json`.

paired 검사는 실행 전후 provider18,474개·자비스19,588개 전체 inventory 및 Node 실행 파일 불변을 확인했다. provider inventory SHA-256 `babb369eec8daf16f72659b34ad4a300c18875bc7ec34a0b3c163dfd5247fb2e`. [상세 결과](INSTALLED-INBOX-PAIR-2026-09-10.json)에 각각의 영수증과 경로를 보존했다.

## 적용 범위

합성 신원·업무·고정 clock을 사용한 실제 연결 경로다. 이번 설치 paired의 native model 호출은0회이며, 앞선 실제 Claude 검증과 Codex 사용량 제한은 [별도 보고서](SCOPED-ACCEPTANCE-CLOCK-2026-09-10.md)를 따른다. 최신 source 전체 pytest를 이번에 다시 실행한 것은 아니다. 기존 전체1,724통과 결과는 이전 제품 기준이고 최근 수집 관련27통과와 구분한다.

운영 current 링크, 서비스, 운영 DB는 변경하지 않았다. 운영 writer/lease 확인과 실제 업무 계보, 전체 에이전트·삭제·복구 수명 등 M1–M14 완료 조건은 유지한다. 준비·paired·maintenance·inbox의 원본 출력은 `/var/tmp/sb-inbox-release-gicqbwxw`에 있다. maintenance 도구의 `--help` 탐색은 argparse 미지원으로 경로 오류가 났으며, 실제 릴리스 경로를 전달한 위 검증은 성공했다.
