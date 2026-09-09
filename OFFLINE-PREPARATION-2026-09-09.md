# 실제 캐시 기반 오프라인 준비 — 2026-09-09

정본 Personal OS manifest의 offline_cache_digest와 reproducibility_receipt는 기존 리허설에서 fixture 값만 사용한다. 그 값을 운영 증거로 복사하지 않고 실제 준비 경로의 오프라인 실행부터 검증했다.

prepare-release.py에 --offline을 추가했다. uv build/export/find/venv/install 자식 실행에 UV_OFFLINE=1을 전달하며 bytecode 단계에도 같은 실행 환경을 유지한다. 앱 wheel의 번들 pip 설치는 기존 --isolated/--no-index/--no-deps를 유지한다. 기본 동작은 바꾸지 않는다.

실측:

- 기존 로컬 캐시로 --offline 준비 성공. strace로 모든 자식의 connect/sendto/sendmsg를 추적했으며 AF_INET/AF_INET6 주소가 기록된 호출0개, trace146행.
- 완성 후보의 실제 TLS/gateway/CLI/MCP4경로와 실행 전후 내용 동일성 검사 통과. 이 통합 검사는 별도 로컬 TLS 통신을 사용하며 오프라인 빌드 trace에 포함하지 않는다.
- 빈 UV_CACHE_DIR로 같은 명령 실행: exit1, 완료 manifest0, 추적한 인터넷 주소 호출0. 중간 release 디렉터리1개는 남는다. 첫 실험에서 '디렉터리도 없다'는 assertion은 실패했으므로 이를 성공으로 표기하지 않았다. 후속 검사에서 미완성 디렉터리와 완료 manifest를 구분했다.
- 관련 준비/helper6개 검사 통과/0.27초, diff check 통과.

[원시 결과](OFFLINE-PREPARATION-2026-09-09.json). 후보: `/var/tmp/sb-offline-preparation-k7u_8lj2/releases/ef56676c6f20ed5ee0fccf3f67563c512bd34756`.

이 플래그는 uv의 네트워크 설정이며 모든 빌드 코드의 네트워크 접근을 커널에서 차단하는 sandbox가 아니다. 관측된 실행에서 IP 연결·전송이 없었다는 결과다. 현재9.5GB 공유 캐시 전체를 고정하거나 복제하지 않았으며 독립 캐시 snapshot digest 및 다른 호스트 재현성은 아직 없다. 정본 manifest의 cache/receipt 필드를 임의 값으로 채우거나 운영 봉인 완료로 표시하지 않는다. 운영 current/DB/서비스 변경 없음.
