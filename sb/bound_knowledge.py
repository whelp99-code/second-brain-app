"""Typed knowledge state for an exact committed page body; not an access grant."""
import re
import unicodedata
from dataclasses import dataclass

from sb.effect_values import JsonValue

type KnowledgeValue = JsonValue | bytes

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True, init=False)
class BoundKnowledge:
    page_id: str
    content_digest: str
    knowledge_status: str
    approval_status: str

    def __init__(
        self, page_id: KnowledgeValue, content_digest: KnowledgeValue,
        knowledge_status: KnowledgeValue, approval_status: KnowledgeValue,
    ) -> None:
        """Parse the four persisted binding columns before publishing a typed record."""
        page = page_id
        if (not isinstance(page, str) or not page.startswith(("wiki/", "daily/", "conflicts/"))
                or page != unicodedata.normalize("NFC", page).lower()
                or any(part in {"", ".", "..", "_proposed"} for part in page.split("/"))
                or "\\" in page or any(ord(c) < 32 or ord(c) == 127 for c in page)):
            raise ValueError("BOUND_KNOWLEDGE_PAGE_INVALID")
        if not isinstance(content_digest, str) or _DIGEST.fullmatch(content_digest) is None:
            raise ValueError("BOUND_KNOWLEDGE_DIGEST_INVALID")
        if not isinstance(knowledge_status, str) or knowledge_status not in {"ACTIVE", "CANDIDATE", "UNKNOWN", "RETIRED"}:
            raise ValueError("BOUND_KNOWLEDGE_STATUS_INVALID")
        if not isinstance(approval_status, str) or approval_status not in {"APPROVED", "PENDING", "UNKNOWN", "REJECTED"}:
            raise ValueError("BOUND_KNOWLEDGE_APPROVAL_INVALID")
        object.__setattr__(self, "page_id", page)
        object.__setattr__(self, "content_digest", content_digest)
        object.__setattr__(self, "knowledge_status", knowledge_status)
        object.__setattr__(self, "approval_status", approval_status)
