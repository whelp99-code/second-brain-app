# R1 evidence classification — 2026-09-28

A result may be cited only in the class that produced it. Promoting a lower class to a higher one is a false pass.

## Classes

| Class | Means | May support | Must not support |
| --- | --- | --- | --- |
| checkout-synthetic | `uv run pytest`, `uv run ruff`, `node --test` in a worktree, fixtures, string-level contract tests | code acceptance rows marked CODE in the R1 plan | installed identity, live source counts, device closure, provider delivery |
| checkout-doc | `git rev-parse`, `git status --porcelain`, file reads, sidecar `git diff --quiet` | P00-1/P00-2/P00-5 documents | production equality |
| real-model | a configured local or remote model process actually invoked, with logs | P10 live-provider rows | nothing yet — NOT_RUN |
| real-server | Ubuntu prod or an approved isolated host, real backup archive, real TLS | P00-3, P07-1, P07-2, P03-T24 | nothing yet — NOT_RUN |
| real-device | physical Mac and/or iPhone, installed Obsidian, signed build | P00-4, P04-1, P04-3, P06-1, P06-2, P06-4, P07-3, P16-17 | nothing yet — NOT_RUN |
| NOT_RUN | command not executed, or executed only as a mock | honesty | PASS |

Installed / real-model / real-server / real-device columns for this baseline are NOT_RUN.

## AC ownership (checkout vs residual)

Issue tracker AC-01–24 stay owned as the work packages state. This file does not close them. It assigns the evidence class each needs.

| AC | Checkout owner if any | Residual that checkout cannot close |
| --- | --- | --- |
| AC-01, AC-02 | L4.C harness named in the plan; not in this tree yet. Earlier store/contract tests exist but are not a substitute citation for the harness. | — |
| AC-03, AC-04, AC-05 | L4.C plus life contract/calendar tests already in tree | device display |
| AC-06 | none | real Mac/iPhone Obsidian (GATED-DEVICE) |
| AC-07, AC-08 | none claimed by R1 lanes as device View | real device |
| AC-09 | L4.C (absent here); surface tests in phase 3 are checkout-synthetic only | real device View |
| AC-10, AC-11, AC-12, AC-13 | model/briefing/question packages; checkout tests where those lanes landed | live model quality sample |
| AC-14 | recall package | live index |
| AC-15 | L4.C (absent here) | — |
| AC-16 | L2.A crash tests are checkout-synthetic; L4.C harness absent | — |
| AC-17 | none | real device View |
| AC-18 | L2.A restore tests checkout-synthetic; L4.C harness absent | live backup archive |
| AC-19, AC-20 | P14, not an R1 lane | — |
| AC-21 | predecessor is P00-3 isolated restore | GATED-PROD. Checkout restore tests do not satisfy the row |
| AC-22 | none | real device permissions |
| AC-23 | parser/security fixtures, checkout-synthetic | — |
| AC-24 | this baseline: full `uv run pytest` and `uv run ruff check sb tests` | real-model column stays NOT_RUN. Phone History pytest and `npm run check` were not part of the recorded AC-24 pair |

## 2026-09-28 citations

| Claim | Class | Citation |
| --- | --- | --- |
| Full Python suite green on this tree | checkout-synthetic | 2527 passed, 3 skipped, 0 failed, exit 0, `/home/jm/.cache/sbt/l4b-logs/pytest-full.log` |
| Ruff clean | checkout-synthetic | exit 0, `/home/jm/.cache/sbt/l4b-logs/ruff-check-sb-tests.log` |
| Obsidian plugin unit tests | checkout-synthetic | 39 pass, exit 0, `/home/jm/.cache/sbt/l4b-logs/npm-test-obsidian.log` |
| Clean worktree at record time | checkout-doc | empty porcelain |
| Sidecars unchanged vs `bdaa363` | checkout-doc | `git diff --quiet` exit 0 |
| Production backup restored | NOT_RUN | — |
| Device Obsidian pull | NOT_RUN | — |
| Provider notification delivered | NOT_RUN | — |

Mock HTTP, fixture CLI providers, and string matches against Swift sources stay in checkout-synthetic even when the test name says "device" or "egress".
