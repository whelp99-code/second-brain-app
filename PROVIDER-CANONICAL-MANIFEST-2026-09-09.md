# 실제 증거 기반 provider 정본 manifest — 2026-09-09

기존 JARVIS Personal OS manifest 형식을 재사용해 실제 provider 후보에 release.manifest.json 및 외부 sidecar를 생성했다. source/build 필드에 fixture 문자열을 넣지 않았다. 생성기는 JARVIS195b1a7 수정이 포함된 별도 emit 모듈을 사용했다.

증거:

- 앱 source d7373ab542e6ed26720817cf8760e2f21e579fde의 tree/first-parent/subject/commit 시각을 Git에서 확인하고, 같은 커밋의 git archive --format=tar 실제 바이트를 해시했다.
- 독립 cache snapshot 해시는2fb2a56e…a9cc72. 각 준비에 그 snapshot의 새 작업 복사본을 사용했다.
- 같은 최종 경로/로컬 환경에서 두 번 준비해18,456개 inventory 항목이 동일했다. [재현성 receipt 원본](PROVIDER-REPRODUCIBILITY-RECEIPT-2026-09-09.json)을 해시해 reproducibility_receipt에 연결했다.
- lifecycle_command_digests에는 [실행한 명령·cwd·캐시 환경 descriptor](PROVIDER-BUILD-COMMAND-2026-09-09.json)의 파일 SHA256을 실행 횟수2회에 맞게 기록했다. 이 기록은 준비 명령2회의 descriptor이며 모든 내부 syscall 목록이라는 뜻이 아니다.

검증 결과:

- 두 준비 결과에서 생성한 정본 manifest 바이트가 일치한다.
- payload18,455항목/412,020,433bytes. root 자체는 JARVIS 형식에 포함하지 않으므로 앞의 inventory 개수와1 차이가 난다.
- 별도 Python 구현으로 파일 목록 누락/추가, 각 파일 해시·크기·권한, 링크 및 전체 domain digest를 검증했다.
- manifest SHA256=`e611b24c62bca76c9bf18358ab67958e90e21a57e0375b87762af71bfd480191`, payload digest=`328942e951f19d02d57cd11db0d2672250c7210e6ab4b5c0e3beeb0196938bf1`. sidecar와 일치.
- manifest 포함 후보의 실제 TLS/gateway/CLI/MCP4경로 및 전후 후보 내용 동일성 검사 통과. JARVIS 소비 실행물은 e6984ad다.

[상세 결과](PROVIDER-CANONICAL-MANIFEST-2026-09-09.json).

manifest 위치: `/var/tmp/sb-manifest-evidence-o0ue1et6/app/releases/ef56676c6f20ed5ee0fccf3f67563c512bd34756/release.manifest.json`.

이 단계는 실제 출처·캐시·재현성 증거를 가진 provider manifest 생성과 검증이다. 파일 쓰기를 영구 차단하거나 배포를 활성화한 것은 아니다. 다른 호스트 재현성·경로 이동·JARVIS 후보의 동등한 봉인·DB 전환·실제 사용자/서로 다른 에이전트 인수는 남는다. 이전 후보를 이동한 첫 사본은 manifest 비교에만 사용했고 이동 후 독립 실행 가능하다고 주장하지 않는다. 운영 current/DB/서비스 변경 없음.
