# 최신 provider 정본 manifest와 실제 연동 검증

제품 `fa798614610074b8cc4aff114b3e977571ff989e`의 재현 가능한 설치 후보에 기존 자비스 Personal OS 형식의 `release.manifest.json`과 외부 sidecar를 생성했다. JARVIS `195b1a7` 격리 빌드의 기존 생성기를 사용했다. 새 manifest 형식이나 계약 예외를 추가하지 않았다.

## 연결한 실제 증거

- Git에서 source commit/tree/first-parent/subject/commit 시각을 읽고 같은 커밋의 git archive 바이트를 SHA256으로 연결했다.
- 관측 캐시 snapshot을 다시 전수 해시해 기존 `2fb2a56e…a9cc72`와 동일함을 확인했다.
- [실행한 빌드 명령 descriptor](LATEST-PROVIDER-BUILD-COMMAND-2026-09-09.json)와 [두 빌드의 재현성 receipt](LATEST-PROVIDER-REPRODUCIBILITY-2026-09-09.json)를 해시해 build 필드에 연결했다. 명령 기록은 실행한 두 준비 명령의 사후 기록이며 모든 내부 syscall의 감사 기록은 아니다.
- 같은 최종 경로에서 생성한 두 빌드의 manifest 바이트가 동일했다. 이동한 첫 사본은 비교 대상으로만 사용했다.
- 독립 Python 구현으로 실제 파일 목록, 해시·크기·권한·링크, payload domain digest 및 sidecar의 manifest SHA256을 대조했다.
- manifest를 포함한 최종 후보에서 실제 TLS/gateway/CLI/MCP 네 시나리오를 다시 실행해 통과했다. 검사 전후 provider/JARVIS/Node 전체 inventory가 동일했다. 모델 호출·업무 내용·인증 주체·시각의 실제 운영 인수와는 구분하며 기존 fixture 한계를 유지한다.

payload18,457항목·412,041,922bytes. 기존 inventory18,458에는 root가 포함되고 정본 payload에는 root가 제외된다. 정본 manifest 자체는 payload에서 제외하며, 최종 연동 inventory에는 manifest도 포함된다.

manifest SHA256: `9737855531136624c8ddacd38e1e94bc2235af638c08e351096136d4f31548ae`.
payload SHA256: `6b42e514e01c20154bf70c1f8fbcac19efb96dc1f32a97b41cbfc8b98c63d33c`.
[전체 결과와 연동 증거](LATEST-PROVIDER-CANONICAL-MANIFEST-2026-09-09.json).

실제 manifest 위치:
`/var/tmp/sb-latest-release-00dj_4mr/app/releases/83ea5fb6703437b674fe08ed2e547f4cc140e624/release.manifest.json`.

## 잔여 조건

이번 결과는 최신 provider 후보의 출처·재현성·내용 검증이다. 파일 쓰기를 영구 차단하거나 운영 활성화한 것은 아니다. 자비스 후보의 동등한 정본 manifest·재현성 및 양쪽 전환 묶음, 모든 writer 종료·재접속 차단, DB58→81 전환/실패 복구, 실제 업무/다른 모델의 공유, 삭제·복원 전체 수명과 M1–M14는 남는다. 운영 current·서비스·DB·자격증명과 다른 저장소 소스를 변경하지 않았다.
