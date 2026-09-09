# 설치 후보 내용 고정 검사 — 2026-09-09

기존 release manifest는 source/wheel/requirements를 기록하지만 설치 이후 파일의 수정·추가·삭제를 검사하지 않는다. `deploy/check-release-contents.py`를 추가해 검증한 실행 후보를 기록하고 전환 직전에 동일 여부를 확인할 수 있게 했다. 운영 경로 자동 연결이나 current 변경은 하지 않았다.

모든 일반 파일의 SHA256·크기·권한, 디렉터리와 심볼릭 링크를 포함하며 bytecode도 제외하지 않는다. 외부 파일 링크는 정규 경로와 referent 해시까지 기록한다. 외부 디렉터리 링크·끊어진 링크·FIFO 등 특수 파일은 거부한다. 파일을 읽는 동안 관측 가능한 변경도 거부한다.

inventory는 후보 밖에 새 파일로만 기록한다. verify는 별도 보관한 inventory SHA256을 요구한다. 따라서 신뢰할 수 있는 SHA256 보관 위치가 전제다.

```bash
python deploy/check-release-contents.py record /absolute/candidate /absolute/outside/inventory.json
python deploy/check-release-contents.py verify /absolute/candidate /absolute/outside/inventory.json --expected-sha256 <별도_보관_SHA256>
```

[실측 요약](RELEASE-CONTENTS-VERIFICATION-2026-09-09.json):

- 관련 pytest 11 passed/0.27초, Ruff 통과. 내용·권한·추가·삭제·링크·외부 실행기·inventory 변조와 외부 디렉터리/FIFO/끊어진 링크 거부 포함.
- JARVIS e6984ad 기반 contained candidate 전체를 임시 복사해 실제 검사 CLI 실행: 19,588항목 정상 → dist/src/cli.js 변경 시 정확히 해당 파일 changed/exit1 → 원래 내용 복원 후 exit0. 임시 복사본 삭제, 원래 후보 미변경.
- SB ebe227c 기반 실제 설치본 읽기 전용 검사: 8,045항목 record/verify 통과. 외부 Python 실행기 링크 3개도 referent 해시로 포함.

이 검사는 특정 시점의 내용 비교다. 최종 검증 후 쓰기가 멈춘 후보에서 기록해야 한다. 실행 중 새 bytecode 생성도 차이로 보고한다. 동시 작성자의 변경·복원이나 검사 이후 쓰기를 막는 봉인 기능, 동적 라이브러리 전체 고정, OS/설정/DB 검증, 운영 승인을 제공하지 않는다. 결과는 항상 activation_authorized=false다. 영구 후보 봉인 및 정본 배포 gate는 남는다.
