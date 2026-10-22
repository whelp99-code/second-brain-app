# Positive internal-mail classification

PR84 admits an automatic SQL record only when the whole ordered
`sb-internal-mail/v1` block parses, its original mail source/digest matches,
all data fields satisfy the rules below, and the installed policy permits
the internal address domain or assignee. A missed veto is not authorization.
Unknown actions, topics, meetings, fields, or ambiguous formats go to
`human_required`; no partial record or automatic completion is produced.

The existing protected-word veto remains an additional guard across metadata.
Its English plural/article forms cover contracts, taxes, payments, invoices,
customer deletion and mail delivery. This is defense in addition to the
positive grammar, not an allow-by-default decision.

## Contact data

- Required fields remain `name`, `email`, in that order. Optional `phone` and
  `department` remain ordered after them.
- Names use a bounded capitalized Latin-name or Korean-name grammar. Arbitrary
  action prose is not a contact format.
- Email uses dot-separated nonempty local atoms and bounded DNS labels. Leading,
  trailing or repeated dots, missing labels, misplaced hyphens, underscores in
  domains, multiple `@`, paths and overlong addresses are refused. The installed
  internal suffix policy still applies; the classifier invents no company domain.
- Optional phone is explicit E.164 (`+` followed by 7 to 15 digits, first nonzero).
- Optional department is one of Engineering, Operations, Sales, Support, Finance,
  HR, 개발, 운영, 인사. An unknown department needs approval.

## Calendar data

The exact permitted titles are Internal standup, Internal review,
Internal planning, 내부 정기 회의, 내부 검토 회의.
Each may have a local identifier, for example `Internal review #project-alpha`.
The identifier starts with a lowercase ASCII letter followed by at most 31
lowercase letters, digits, underscores or hyphens; it is not a free-text task.

Valid instants, increasing start/end, supported timezone and the installed
internal assignee remain required. An external invitation, attachment or arbitrary
calendar title does not become an internal meeting through this format.

## Progress notes

The exact permitted subjects are Internal review, Internal note, Internal status,
내부 검토, 내부 메모, 내부 진행 현황, with the same optional local identifier.
Existing statuses remain noted, in_progress, waiting_internal.

`next_internal_action` must exactly equal one of:

- `file the note`
- `record internal status`
- `review internal note`
- `내부 메모 정리`
- `내부 진행 상태 기록`

Prefixes, appended recipients/instructions, numeric or written budgets,
transfers, contracts, customer deletion, sending, forwarding, attaching,
uploading and unknown prose are not automatic actions. For example,
`file the note then forward it` is not `file the note`.

## Evidence boundary

`test_company_internal_classifier.py` exercises the owner classifier.
`test_company_db_classifier_boundary.py` exercises the actual DB provider,
original policy/transition receipts, claims, effects and final candidate state.
`python -m tests.company_classifier_boundary_smoke --root <new-isolated-root>`
proves the rejected corpus plus genuine internal contact/calendar/progress rows
through the real pipeline. Only the NV anchor is simulated.

Revocation, deduplication, original pending recovery and restore checks are not
changed by this correction. A surviving independent anchor rejects restored
DB/witness state; restoring the anchor itself is not a software-provided
anti-rollback guarantee. No production provisioning or activation is performed.
