# Second Brain production approval package

Date: 2026-09-27
Feature branch: `feat/sb2-life-intelligence-20260926-6c57b834`
Checkout proof HEAD at classification: `2ba7154eeef5a955a6ccd89107d79711c05a4d7c`
Measured release: `c00f378292eac0f07b52bab70df0bb0132c5d539`
Release source commit: `ffaf19009ba9e74fe721a5767abb8cee8fa0a588`

실행하지 않음. This package lists owner decisions. None of the actions below were executed by the loop that wrote this file.

Recommendation: do not switch `app/current`, do not restart units, do not push `origin/master`, and do not start collectors until each item is answered separately.

## a. DSN

The configured unified-db host and `127.0.0.1:5433` are unconfirmed as the same database. 단정하지 않음. No DSN was read from the secret config and no DSN change was applied. If they are later shown to be the same database, the exact DSN change still needs a separate approval.

## b. refresh

Do not start `jm-second-brain-refresh.timer` until item a is answered. The unit was observed failed earlier and was not restarted.

## c. app/current

Do not build a new release and do not switch `/home/jm/.local/state/second-brain/app/current`. It still points at `c00f378292eac0f07b52bab70df0bb0132c5d539`.

## d. second-brain-web

Do not restart `second-brain-web.service`. Its ActiveEnterTimestamp at measurement was Wed 2026-09-23 11:03:30 KST.

## e. phone-history

Do not start `phone-history.service`. Do not run physical-device validation. The checkout retention test passed; that is not device acceptance.

## f. hybrid

Do not set production `[search] hybrid = true`. Do not seal a new production generation. Fixture hybrid tests passed with the flag off in production.

## g. origin/master

Do not push or fast-forward `origin/master`. It remains `9437b6e24b34a25d8bc1d090a8064cbaad57a7fc`. The feature branch push already approved by 커푸 is not this item.
