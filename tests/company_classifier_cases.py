"""Synthetic request-boundary inputs shared by classifier and real DB probes."""

from __future__ import annotations

from typing import Final

from tests.company_internal_auto_support import calendar_body, contact_body, progress_body

REPORTED_ACTIONS: Final = (
    ("reported-external-email", "거래처에 이메일 보내기"),
    ("reported-budget-approval", "예산 이백만원 집행 승인"),
    ("reported-purchase-order-forward", "발주서 승인 후 협력사에 전달"),
)

ACTION_VARIANTS: Final = (
    ("numeric-budget", "예산 2000000 집행 승인"),
    ("grouped-budget", "예산 2,000,000 집행 승인"),
    ("fullwidth-budget", "예산 ２００００００ 집행 승인"),
    ("written-budget", "예산 이백만 집행 승인"),
    ("written-money", "이백만 원 집행"),
    ("english-written-budget", "approve budget two million"),
    ("currency-budget", "집행 2M KRW"),
    ("external-address", "자료를 partner@vendor.example 로 공유"),
    ("suffix-confusion", "자료를 partner@mail.internal.vendor.example 로 전달"),
    ("attachment", "첨부 자료 검토 후 전달"),
    ("attach-document", "문서 첨부하기"),
    ("upload-document", "문서를 업로드하기"),
    ("share-file", "share attachment with vendor"),
    ("forward-file", "forward attachment to colleague"),
    ("reply-email", "거래처 메일 회신"),
    ("polite-send", "협력사에 보내 주세요"),
    ("transmit-email", "메일 전송하기"),
    ("call-customer", "고객에게 전화하기"),
    ("notify-customer", "고객에게 알림"),
    ("send-message", "send a message"),
    ("forward-note", "forward the note"),
    ("notify-recipient", "notify external recipient"),
    ("allowed-prefix", "file the note then forward it"),
    ("allowed-action-recipient", "file the note to customer"),
    ("unicode-separator", "file the note　to customer"),
    ("ambiguous-task", "내부 검토 후 적절하게 처리"),
    ("attached-instructions", "follow the attached instructions"),
    ("unknown-task", "arrange something"),
    ("implicit-completion", "완료로 처리"),
)

INVALID_EMAILS: Final = (
    ("reported-dot-address", "..@mail.internal"),
    ("leading-dot", ".ada@mail.internal"),
    ("trailing-dot", "ada.@mail.internal"),
    ("consecutive-dot", "ada..lovelace@mail.internal"),
    ("missing-local", "@mail.internal"),
    ("double-at", "ada@@mail.internal"),
    ("missing-domain-label", "ada@mail..internal"),
    ("leading-domain-hyphen", "ada@-mail.internal"),
    ("trailing-domain-hyphen", "ada@mail-.internal"),
    ("domain-underscore", "ada@bad_mail.internal"),
    ("trailing-domain-dot", "ada@mail.internal."),
)

ENGLISH_ACTIONS: Final = (
    ("plural-contracts", "contracts"),
    ("plural-taxes", "taxes"),
    ("plural-payments", "payments"),
    ("plural-invoices", "invoices"),
    ("customer-article", "delete the customer"),
    ("mail-to-customer", "send mail to customer"),
    ("customer-removal", "고객 제거"),
    ("english-wire", "wire two million to supplier"),
    ("english-remittance", "remit funds"),
    ("english-forward", "forward a message to vendor"),
    ("english-contract-approval", "approve contracts"),
    ("english-purchase", "execute purchase agreement"),
)


def unsafe_cases() -> tuple[tuple[str, str], ...]:
    progress = tuple(
        (label, progress_body().replace("file the note", action))
        for label, action in (*REPORTED_ACTIONS, *ACTION_VARIANTS, *ENGLISH_ACTIONS)
    )
    addresses = tuple((label, contact_body(email=email)) for label, email in INVALID_EMAILS)
    external = (
        ("contact-external", contact_body(email="ada@vendor.example")),
        ("contact-suffix", contact_body(email="ada@mail.internal.vendor.example")),
        ("contact-path", contact_body(email="ada@mail.internal/vendor.example")),
    )
    moved = (
        ("progress-subject", progress_body().replace("Internal review", REPORTED_ACTIONS[0][1])),
        ("calendar-title", calendar_body().replace("Internal standup", REPORTED_ACTIONS[2][1])),
        ("calendar-unknown", calendar_body().replace("Internal standup", "Something ordinary")),
        ("contact-name", contact_body(name=REPORTED_ACTIONS[0][1])),
        ("contact-department", contact_body() + "department: " + REPORTED_ACTIONS[1][1] + "\n"),
        ("contact-phone", contact_body() + "phone: " + REPORTED_ACTIONS[2][1] + "\n"),
    )
    named = tuple(
        ("contact-" + label, contact_body(name="Ada " + action.title()))
        for label, action in ENGLISH_ACTIONS
    )
    bare_named = tuple(
        ("contact-bare-" + label, contact_body(name=action.title()))
        for label, action in ENGLISH_ACTIONS
    )
    return (*progress, *addresses, *external, *moved, *named, *bare_named)
