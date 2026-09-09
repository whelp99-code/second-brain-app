"""Typed knowledge state for an exact committed page body; not an access grant."""
import re
import unicodedata
from dataclasses import dataclass

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class BoundKnowledge:
    page_id: str
    content_digest: str
    knowledge_status: str
    approval_status: str

    def __post_init__(self) -> None:
        page = self.page_id
        if (not isinstance(page, str) or not page.startswith(("wiki/", "daily/", "conflicts/"))
                or page != unicodedata.normalize("NFC", page).lower()
                or any(part in {"", ".", "..", "_proposed"} for part in page.split("/"))
                or "\\" in page or any(ord(c) < 32 or ord(c) == 127 for c in page)):
            raise ValueError("BOUND_KNOWLEDGE_PAGE_INVALID")
        if not isinstance(self.content_digest, str) or _DIGEST.fullmatch(self.content_digest) is None:
            raise ValueError("BOUND_KNOWLEDGE_DIGEST_INVALID")
        if not isinstance(self.knowledge_status, str) or self.knowledge_status not in {"ACTIVE", "CANDIDATE", "UNKNOWN", "RETIRED"}:
            raise ValueError("BOUND_KNOWLEDGE_STATUS_INVALID")
        if not isinstance(self.approval_status, str) or self.approval_status not in {"APPROVED", "PENDING", "UNKNOWN", "REJECTED"}:
            raise ValueError("BOUND_KNOWLEDGE_APPROVAL_INVALID")
