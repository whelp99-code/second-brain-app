# 최신 수정본 설치·자비스 연동·재현 검증

제품 커밋 `fa798614610074b8cc4aff114b3e977571ff989e`를 독립 캐시 사본으로 offline 준비했다. 최근 canonical 검색 ID, 명시적 registry, 공통 마스킹, 각주 중복 수정이 들어간 최신 후보를 대상으로 검증했다.

후보: `/var/tmp/sb-latest-release-00dj_4mr/app/releases/83ea5fb6703437b674fe08ed2e547f4cc140e624`.

## 실행과 증거

1. 기존 읽기용 snapshot `/var/tmp/sb-cache-tool-acceptance-uc9xys96/snapshot`을 이번 작업 전용 cache에 복사했다. `UV_CACHE_DIR`을 해당 사본으로 지정해 `python deploy/prepare-release.py --offline /var/tmp/sb-latest-release-00dj_4mr/app` 실행. 빌드 대상은 Git archive이며 미추적 백업을 포함하지 않는다.
2. 설치된 Python 패키지와 자비스 `195b1a7` 격리 빌드 `/var/tmp/jarvis-current-pair-_mq15nmd/source/dist`로 check-release-integration.py 실행. Node24.19.0 사용. 정상 쓰기→provider proved→자비스 settled/control completed→새 로그인 회수, 접수 중 철회, 실행 전 철회·만료의 네 시나리오 통과. 실제 TLS·gateway·CLI·MCP를 사용했으며 identity/clock/업무 내용은 fixture다.
3. 연동 종료 후 첫 후보와 사용한 캐시를 작업 전용 다른 경로로 보관했다. snapshot의 새 사본으로 **같은 최종 경로**에 동일 명령을 다시 실행했다. 두 준비 결과의 전체18,458항목 inventory가 같았다. 이동한 첫 사본을 실행 가능한 별도 설치물로 주장하지 않는다.
4. 설치된 sb 파일176개를 source commit의 Git blob과 전수 비교했다. 빠지거나 추가된 앱 파일 없음. bytecode는 별도 전체 inventory에 포함된다.
5. 최종 후보 inventory digest가 첫 후보의 연동 전후 digest와 일치함을 확인했다. 연동 검사 중 provider/JARVIS/Node 내용 변경 없음.

provider inventory SHA256: `fb76df86dec192515eef9d113f9abb9eec79fd8b8ab9a3f44bf8275254c934bc`.
자비스19,588항목 SHA256: `8b3ebc1901256636f33c6218adee47d6e294355afd64b569af343ea7676b8d10`.
[전체 실행 증거](LATEST-INSTALLED-PAIR-2026-09-09.json).

## 남은 운영 전환 조건

이번 후보에는 준비 도구의 release-manifest.json이 있다. 최신 후보용 JARVIS 정본 release.manifest.json·sidecar 및 양쪽 운영 전환 묶음은 아직 완성하지 않았다. 재현 검증은 같은 호스트·최종 경로·관측 캐시 조건이며 다른 호스트 재현성을 보장하지 않는다. 최초 연동 후 두 번째 후보를 다시 연동한 것이 아니라 전체 inventory 일치로 동일성을 확인했다.

운영 current·서비스·DB·자격증명을 변경하지 않았다. 모든 writer 종료와 재접속 방지, DB58→81 전환 및 실패 복구, 실제 업무/다른 모델 에이전트 공유, 전체 삭제·복원 수명과 M1–M14 인수는 남는다. 이전 전체1,551통과는 각주 수정 전이며 각주 수정 후 관련47통과와 이번 설치 연동 결과를 별도로 유지한다.
