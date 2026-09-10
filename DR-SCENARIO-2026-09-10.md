# M12 DR 시나리오 — 격리 복원 실측

[인계 보완](CODEX-REPLY-REVIEW-2026-09-10.md) 5.5. 후보 `c04dee1`의 `bin/sb`만 사용했다. 운영 `current` 링크·서비스를 바꾸지 않았다. 운영 백업 파일은 읽기만 하고 복원 목적지는 `/var/tmp/sb-m12-dr/`이다.

기존 [원장 소실 거부](RESTORE-ANCHOR-LOSS-GATE-2026-09-10.md)는 안전한 거부를 복구 완료로 치지 말라고 못 박는다. 이번 실행은 그 거부를 뒤집지 않는다.

## 시나리오와 실측

| 시나리오 | 하는 일 | 하지 않는 일 | 실측 |
|---|---|---|---|
| A. 빈 journal / 원본 세대 근거 없음 | 기존 sanitizer 검사 | 백업 주장으로 운영 anchor 생성 | [거부 게이트](RESTORE-ANCHOR-LOSS-GATE-2026-09-10.md) `RESTORE_SOURCE_ANCHOR_MISSING`. 이번 재실행 없음 |
| B. 작은 격리 vault 백업→검증→`--to` 복원 | `sb init`·`remember`·`backup`·`verify-backup`·`restore --to` | 운영 경로 | backup 0.30s, verify 0.27s, restore 0.25s, 25파일 / 426KB, exit 0 |
| C. 운영 tarball을 격리 디렉터리로 복원 | 최신 운영 백업을 `--to /var/tmp/...` | `current` 교체, tombstone 하향 | restore exit 0, 6.69s, 17,386파일 / 38.8MB |
| D. 같은 tarball을 `/var/tmp` 복사본에서 아카이브만 검증 | `verify_backup(archive)` — 운영 journal 잠금 없음 | 운영 `backups/`에 receipt/temp를 쓰지 않음 | **7.42s, ok**, 17,386파일 / 38.8MB, sha256 `a099f592eebee1aa4d21e86d447aca59af310491985c5d93aa65bf49d46a4300` |

운영 백업: `/home/jm/.local/state/second-brain/backups/second-brain-20260910T032857+0900.tar.gz` (14,990,156 bytes).

처음 C의 `verify-backup` exit 1 `BACKUP_TOMBSTONE_OR_PROVIDER_MISMATCH`는 **후보 wheel이 운영 백업을 못 읽는다는 뜻이 아니다.** tiny 실험 설정의 현재 tombstone/provider를 운영 아카이브 세대와 대조했기 때문이다. 설정 바인딩 검증은 다른 vault에 대해 실패하는 것이 맞다. 아카이브만 복사해 검증하면 후보 `c04dee1`에서 통과한다.

격리 `restore` 성공을 운영 복구 완료로 치지 않는다. 복원본은 권한·삭제 high-water·검색을 재증명한 것이 아니다.

JSON: [DR-SCENARIO-2026-09-10.json](DR-SCENARIO-2026-09-10.json).

## RPO / RTO (이 실행이 말할 수 있는 범위)

- **SB 파일 백업 RPO:** 운영 타이머 `jm-second-brain-backup`은 이 세션에서 inactive였다. 사용한 tarball 시각은 2026-09-10 03:28 KST. 관측 시각 20:39 KST이면 이 사본 기준 손실 창은 **약 17시간**이다. 15분 JARVIS sqlite 타이머와 섞지 않는다.
- **RTO 표본:** 운영 규모 아카이브를 빈 격리 디렉터리에 푸는 벽시계 **6.69s**. 검증·권한 재결합·검색 재구축·writer 배제·서비스 재개를 포함하지 않는다.
- 원장 journal 소실 시 자동 복구 RTO는 **없다**. 현재 완료 조건은 거부이며 복구가 아니다.

## 완료로 올리지 않는 이유

1. 독립 세대 근거와 운영 원장 digest가 모두 맞는 상태 복원 후보다가 아니다.
2. 복원 후 조회·범위 거부·삭제 억제를 이 목적지에서 인수하지 않았다.
3. 운영 journal에 묶인 verify는 산 운영 경로를 잠그므로 전환 런북에 별도 절차가 필요하다. 아카이브 단독 검증은 복사본에서만 한다.

M12를 완료 처리하지 않는다.
