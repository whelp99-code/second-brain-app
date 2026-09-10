# 최신 전체 회귀 코드의 설치 인수

소스92db131fbd54e2d5e6df41b173fca9668d7ecb9e의git archive로offline설치 후보를 만들었다. 제품은 전체1724통과/2skip을 기록한6b3c906과 같으며 이후문서수정만포함한다. 검색·콘솔·inbox최근수정을포함한다.

후보 `/var/tmp/sb-current-release-3r2yh1_u/releases/6f7b6b73915ac6834460108bbb98ed9973ebd02e`.

기존 `deploy/check-release-integration.py` 및 `deploy/check-release-maintenance.py`를 순차실행해 모두exit0. 설치된Python/CLI를 사용하며 sb소스트리에서제품을import하지 않는다. 자비스는 기존격리build를 사용했다.

- 실제TLS/gateway/MCP쓰기/CLI실행:provider proved→자비스settled/control completed→새로그인/독립2reader각2records,같은generation.
- replay settlement1/attempt1,외래키오류0,reader철회403.
- 접수중철회denied,실행전철회/만료failed·세대미활성화.
- paired검사전후 SB18,474항목/JARVIS19,588항목 및Node파일동일.
- 설치maintenance:live잠금busy보존→workerSIGKILL(-9)후임시workspace1개정리→재실행0. 각단계새프로세스에서기존기억1건조회와generation/body/ledger/highwater일치,총3회보존확인.

[전체구조화증거/manifest](CURRENT-INSTALLED-ACCEPTANCE-2026-09-10.json). 신원/원문/정책/clock합성fixture이며 native모델호출0. 운영current·서비스·DB변경없음. 실제사용자task계보·native전체수명·운영전환·남은파일이동경합 및 M1–M14전체인수는계속남는다. 이번에는제품수정을추가하지않았다.
