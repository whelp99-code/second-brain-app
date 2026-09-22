# Codex 야간 독립 검토 — 713e453

판정: **전체 인수 미통과 / 최종 완료 아님**. 이전 V1-F 동일 본문·별도 기록 충돌은 이번 고정 후보에서 해결됐다. 새 dispatch 결함은 이번 실행에서 발견하지 않았다. 남은 승인 범위의 다음 작업은 M12 JARVIS 자체 복구·RPO와 B/F 최종 핀 복구 준비다. 실제 native 인증/세션 compaction/사본 수명은 별도 미검증 조건이다.

작성자: 기존 Codex 감시 작업 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`. 원래 Codex가 직접 실행한 검토가 아니다. 검토 시각 UTC 2026-09-11T23:38:52.409247+00:00. 정본 A–F, 원 M1–M14, 26cf158/d26dd7a 및 후속 야간 검토 판정을 이어받는다. 미검증 범위를 축소하거나 fixture 통과를 운영 인수로 치환하지 않는다.

## 고정 후보와 바이트 확인

- SB 제출 `713e453e69ef9bf0232d7cfc5ff04deca3b11509` / source `8d80a3a2749824059a2beb919dbf4db537dd5c08`.
- release `0ecdb5617a1fe95697e55366f631ee4373f407b1` / wheel SHA256 `0e32b787c97a42d922132e93e3c67ab375d06154b433d23a042283112cbf0b57`.
- 설치물 `/var/tmp/sb-candidate-8d80a3a/releases/0ecdb5617a1fe95697e55366f631ee4373f407b1`. archive/wheel/설치물 Python 182개 동일.
- JARVIS `f9e079148f25217ac5bc7c482482cd9d63053752` / dist `/var/tmp/jarvis-artifact-f9e0791/source/dist`. tracked product 1137개 동일, 독립 tsc 재빌드 JS 1109개 동일.
- inventory `650c79d62cba1c27c1db06cf403f8bd2ffa73dffd45f7290148dc86b655f826e`, 34768 entries, 검사 전후 동일. dispatch JS `8d95e3d41880bdece0585a42242ccfa0ed82062c9e44577a63b523ff144d8456`.
- 증거와 harness: `/var/tmp/codex-night-713e453-azk05juq`. Vitest는 독립 복사본에서 실행하여 후보 cache를 변경하지 않았다. SB 제품 바이트가 같아 전체 pytest를 이유 없이 반복하지 않았다.

## 직접 실행 결과

| 검사 | 결과 및 한계 |
|---|---|
| GJC dispatch + assembled session | 30 passed, 24.95초, EXIT 0; `jarvis-focused.log` |
| Ruff / JARVIS tsc | 각각 EXIT 0; `ruff.log`, `jarvis-tsc.log` |
| revoked_keys 타입 검사 | 0 errors, 2 warnings, **EXIT 1**. os.write 미사용 반환 경고; 전체 타입 통과라고 표시하지 않음 |
| 설치 standard/work/maintenance | 3개 EXIT 0; `installed-*.log`; 격리 설치 게이트 |
| paired restore | EXIT 0; `paired-restore.log`, `paired-restore-result.json` |

위 수치는 이 Codex 감시 작업이 직접 실행한 값이며 Grok 제출 수치를 합산한 것이 아니다.

V1-F: `dispatch-same-content-records.mjs/.json`에서 본문·출처·시각이 같고 sid/record_id가 다른 두 기록을 실제 `gjc.dispatch` 진입점에 제공했다. send 1, 643 bytes, 영속 memory/evidence 2/2와 서로 다른 evidence_id/binding 2개를 확인했다. JARVIS `src/cli-gjc-commands.ts:317,328`의 digest+reference 기반 ID 대응이 이전 첫 evidence 재사용을 해결한다.

회귀: `dispatch-persisted-lineage.json` 두 기록 send1/641bytes/영속2+2; `dispatch-final-budget-2048.json` total2048/excerpt128 제한에서 장문 생략 후250bytes; `dispatch-before-send-generation.json` 전송 전 세대 거부 send0 뒤 정정 재시도 send1; `dispatch-newsession-generation.json` 구성된 새 세션 재조회 및 negative 뒤 세대 변경 차단. `dispatch-inner-negative-crash.json`은 실제 child exit99 후 새 프로세스 재시도에서도 remote accept1/retry send0/unknown을 보존했다. synthetic provider와 주입 transport를 통한 제품 함수 경계 검증이며 native 모델 인증이나 실제 compaction 이벤트 인수가 아니다.

## 미충족 M12-B-F — 같은 복구 계약을 끝낼 것

정본 `scripts/jarvis-restore-acceptance.mjs`는 SB journal2 유실/백업복구, JARVIS 삭제→SB restore, scoped2 client의 같은 세대/본문 및 독립 철회2, 실제 새 write proved, high-water2 이후 재복원0을 통과한다. 검토 복사본은 Python interpreter 경로만 이 환경의 실제 venv로 바꾸었다. 일반 제품 복구 결함으로 harness 환경 차이를 세지 않는다.

측정된 격리 RTO: restore→첫 읽기 **1579ms**, 장애 시작→첫 읽기 **7481ms**, 장애 시작→scoped+새 write 가능 **10031ms**. 전체 시나리오16758ms와 구분한다. 최근 last_durable 시각을 effects.apply의 proved 반환 뒤로 옮긴 것은 개선이다. 다만 그 receipt는 삭제 효과이며 **JARVIS DB는 시험 내내 살아 있다**(`scripts/jarvis-restore-acceptance.mjs:30,131–138`). JARVIS 자체 백업/유실/복구가 없고 `crash_loss_after_last_durable:0`은 상수다. 이것으로 JARVIS 자체 RPO0을 인수할 수 없다. SB도 백업 후 장애 전 쓰기0인 fixture다.

완료 기준: 기존 지원 복구 경로를 사용한 격리 JARVIS authority/journal 백업→자체 유실/재시작/복구를 실행하고, 장애 전 마지막 durable receipt와 복구된 accepted receipts/state를 비교하여 시스템별 손실량·시점을 계산한다. 삭제 high-water, scoped 접근, 새 업무 accepted/proved까지 함께 검증한다. 운영 authority/config/auth를 복사하거나 실제 사용자 기록에 장애를 주지 않는다.

`GROK-PIN-RECOVERY-RUNBOOK.md`의 현재 source 서비스파일 hash 앞16자는 7개 모두 대조됐다(전체값 `runbook-source-hashes.json`). 이는 배포 설정/실제 백업 manifest hash가 아니다. 현재 복구 명령의 ROOT/REL/JARVIS가 구체화되지 않았고 restore에 필요한 trusted JARVIS fence 전달이 빠졌다. 후속 harness는 자체 새 fixture를 생성하므로 앞 명령의 ROOT를 이어 복구하는 절차로 볼 수 없다. 운영 current41f0751 유지라는 문구 자체는 구버전 호환 검증이 아니다.

완료 기준: 최종 full pin, 서비스·설정·백업 manifests/hash, 신뢰 fence 입력의 출처/전달 명령, writer lease 배제 증거(큐0과 구분), 격리에서 확인한 구버전 호환 또는 안전한 거부/복구 경로를 실행 가능한 순서로 준비한다. 실제 운영 drain/전환은 별도 외부 승인으로 남긴다. 소스 checksum 추가만으로 이 준비가 끝났다고 하지 않는다.

## 기존 미충족과 다음 행동

A–F/M1–M14 상태표는 원 의미를 유지하고 직접 증거/기존 로그/미검증/외부 입력을 구별한다. explicit configured dispatch 통과를 M8 제품별 native 연결, M9 실제 문맥 compaction, M5 native 사본 수명 완료로 확장하지 않는다. M10 실제 한국어 질의 ground truth, M11 운영 규모/정정 성능, M13 전체 GUI와 실제 외부 제품 조건은 오전 보고 및 이전 검토의 미충족을 유지한다. 새 기능을 만들어 검증량을 채우지 않는다.

기존 Grok의 현재 승인 native goal을 공식 기능으로 재개하여 **M12 자체 복구와 B/F 준비를 하나의 관련 작업으로** 끝내고, 통합 상태표·정확한 외부 입력·일관된 hash를 갖춘 후보를 제출한다. 운영 전환/인증 복사/사용자 삭제/push는 승인하지 않았다. 30분 감시는 유지한다.
