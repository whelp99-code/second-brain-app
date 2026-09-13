# 현재 후보 운영 판단 (미실행, a48cd07 N4)

전환·재시작·백업을 실행하지 않는다. 당일 current/hash는 점검 대기.

## 대상 (이번 제출)

- SB: `/var/tmp/sb-candidate-f8c7bcd/releases/7e52e867e67215baa5ff10f29207eb914f849ae6/bin/sb`
- JARVIS dist: `/var/tmp/jarvis-artifact-a3c111c/dist/src/cli.js`
- 운영 current (인용만): SB `41f0751`, JARVIS authority `a3cbbbe`, `production_activated=false`

## 비밀 없는 설정 변경안 (미적용)

Claude **격리** settings 예시 (운영 `~/.claude` 금지):

```json
{
  "hooks": {
    "PostCompact": [{ "hooks": [{ "type": "command", "command": "env SB_CONFIG=/var/tmp/sb-client-readiness/config.toml /ABS/bin/sb postcompact-hook" }] }],
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "env SB_CONFIG=/var/tmp/sb-client-readiness/config.toml /ABS/bin/sb postcompact-hook" }] }]
  }
}
```

JARVIS 호스트:

```
export JARVIS_MODEL_TRANSPORT_PATH=/var/tmp/sb-client-readiness/model-capture.jsonl
export JARVIS_SECOND_BRAIN_LAUNCHER=/ABS/bin/sb
export JARVIS_SECOND_BRAIN_CONFIG=/var/tmp/sb-client-readiness/config.toml
node /var/tmp/jarvis-artifact-a3c111c/dist/src/cli.js memory postcompact --db /ABS/authority.sqlite
```

`MEMORY_REFERENCE_OPTIONS_REQUIRED`는 transport 경로 없음이지 로그인 부족이 아니다.

## 전환 순서 (승인 후, 지금 실행 금지)

1. 당일: `readlink` SB `/home/jm/.local/state/second-brain/app/current`, JARVIS `/home/jm/.local/state/orca-jarvis/authority/current`; `systemctl --user is-active jm-jarvis.service jm-jarvis-dashboard.service jm-jarvis-phone-gateway.service`; 백업 파일 hash.
2. writer/lease: `python3 deploy/check-jarvis-pending-state.py`; `python3 deploy/check-database-handles.py`. 큐 0으로 대체하지 않음.
3. 중단: `systemctl --user stop jm-jarvis.service jm-jarvis-dashboard.service jm-jarvis-phone-gateway.service` (requests.service는 oneshot; timer not-found를 장애로 단정하지 않음).
4. current를 **새 후보 절대 경로**로 교체. 구버전 링크만 되돌리지 않음.
5. 기동: 위 서비스 start.
6. 성공: `SB_CONFIG=… sb doctor` EXIT0, 서비스 active, `sb search` 1건, PostCompact `{}` 후 UserPromptSubmit additionalContext.
7. 실패 단계별 복구: 기동 실패→ stop 후 **백업 집합**(DB+vault+authority) 복원 후 start. 보류 보안/삭제 검증을 통과로 전제하지 않음.

과거 RSS/DR 시간은 7d97af7/c04dee1/b9fc3d4 핀 한계. 현재 운영 크기·RPO/RTO 미확정.
