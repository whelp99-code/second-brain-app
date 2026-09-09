# 독립 오프라인 캐시 검증 — 2026-09-09

공유 uv 캐시9.5GB에 의존하던 준비 과정을 파일 syscall 추적으로 대조했다. `deploy/snapshot-observed-uv-cache.py`는 관측된 archive-v0 패키지 디렉터리 전체와 인덱스 metadata를 복사한다. 임시 생성 항목은 제외하고 cache 내부 링크를 새 위치의 상대 링크로 연결한다. 외부 링크·기존 대상 덮어쓰기를 거부하며 전체 inventory를 해시한다. 추적에서 없었던 입력까지 완전하다고 주장하지 않으므로 생성 결과의 offline_completeness_verified는 false다. 반드시 실제 오프라인 준비로 검증한다.

실측:

- 최초 추적63,279,153bytes. 선택된 archive180개·일반파일14,738개·697,241,804bytes를 확인했다. 이 숫자는 archive 내용이며 인덱스까지 포함한 전체 cache 크기와 구분한다.
- 도구 생성 결과: 관측 경로8,048개, snapshot 전체17,396항목. cache_entries_sha256=`2fb2a56e3be2f06fe4d1b5ee23a64878d48abb9fbff9c6ec142bfcaf7ea9cc72`.
- snapshot을 별도 working cache로 복사하고 UV_CACHE_DIR를 그 경로로 지정해 --offline 준비 성공. 모든 자식의 파일/연결/전송 syscall 추적에서 기존 공유 캐시 참조0·인터넷 주소 참조0.
- 준비 후 snapshot 전체 해시가 같음을 확인했다. working cache는 빌드가 사용하는 쓰기 가능한 복사본이다.
- 이 후보의 실제 TLS/gateway/CLI/MCP4경로 및 후보 전후 내용 동일성 검사 통과.
- 관련13개 통과/0.30초, Ruff(새 도구/테스트)·diff check 통과. [원시 검증 결과](INDEPENDENT-OFFLINE-CACHE-2026-09-09.json).

snapshot: `/var/tmp/sb-cache-tool-acceptance-uc9xys96/snapshot`

후보: `/var/tmp/sb-cache-tool-acceptance-uc9xys96/app/releases/ef56676c6f20ed5ee0fccf3f67563c512bd34756`

사용 순서: 준비 명령의 strace 파일 추적 → `python deploy/snapshot-observed-uv-cache.py TRACE CACHE NEW_SNAPSHOT` → snapshot의 작업 복사본 생성 → 해당 UV_CACHE_DIR에서 --offline 준비 → snapshot hash 및 실제 설치본 검증. trace 자체는 cache 선택을 위한 관측 자료이며 고정 입력 완전성의 증명은 아니다.

현재 입력/호스트의 실제 실행에 대한 증거다. 다른 의존성/플랫폼, 모든 OS 도구·관리형 Python 원본·설정의 독립성, 악의적 동시 cache 변경, 영구 보존/봉인까지 증명하지 않는다. 정본 manifest 작성·운영 전환·실제 사용자/에이전트 인수는 남는다. 운영 current/DB/서비스 변경 없음.
