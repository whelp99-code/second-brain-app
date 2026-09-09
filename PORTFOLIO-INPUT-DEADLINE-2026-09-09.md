# Portfolio stdin 대기 제한 — 2026-09-09

JARVIS src/dashboard/portfolio-stdin.ts에 60초 전체 입력 deadline을 추가했다. 기존 수집기 subprocess 제한 30초보다 여유를 두며, 무한 열린 입력은 허용하지 않는다. timeout이면 Readable을 PORTFOLIO_INPUT_TIMEOUT 오류로 destroy하고 read를 reject한다. 정상/오류 종료 모두 타이머를 해제한다. 기존 128KiB 크기 제한과 바이트 보존은 유지한다. CLI execute의 기존 finally db.close로 오류가 전달된다.

검증: stdin4개·portfolio CLI4개·collector CLI1개 총9개 통과(6.60초), ESLint 통과, 별도 TypeScript emit/migration 복사 통과. fake timer로 끝나지 않는 부분 입력의 reject/destroy/타이머 해제와 정상 완료 해제를 확인했다.

별도 실행물 /var/tmp/jarvis-stdin-deadline-7pmxb_ho/src/cli.js의 실제 portfolio ingest를 임시 migrated DB/fixture key로 실행했다. stdin에 ‘{’를 보내고 EOF를 보내지 않았다. 60,211ms 뒤 exit2/PORTFOLIO_INPUT_TIMEOUT으로 자체 종료했고 guard kill은 실행되지 않았다. stdout 성공 응답 없음, 이후 DB 재개 및 migration readiness 통과. 입력 timeout에서 실제 DB 프로세스가 무기한 남는 현상을 제한한 증거다.

운영 프로세스 PID1553366을 종료하거나 운영 릴리스를 교체하지 않았다. 현재 살아 있는 구버전에는 이 변경이 적용되지 않는다. 느린 생산자가 60초를 넘기면 입력을 거부하는 동작 변화가 있으며 자동 재전송하지 않는다. 과거 SSH 호출 주체 확인과 운영 전환 절차는 남는다. 전체 M1–M14 미완료.
