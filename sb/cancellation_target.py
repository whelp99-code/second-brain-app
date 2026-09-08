"""Actual generation and committed target verification for cancellation admission/execution."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from sb.correction_cancellation_models import CorrectionCancellationIntentV1
from sb.generations import Generation
from sb.search import git_run


class CancellationTargetError(RuntimeError):
    pass


MAX_TARGET_PAGE_BYTES = 16 * 1_048_576


def _page_bytes(root: Path, relative: str) -> bytes:
    path = root / relative
    if (Path(relative).is_absolute() or ".." in Path(relative).parts
        or not relative.startswith(("wiki/", "daily/", "conflicts/"))
        or not path.parent.resolve().is_relative_to(root.resolve())):
        raise CancellationTargetError("EFFECT_TARGET_INVALID")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            metadata = os.fstat(descriptor)
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                or metadata.st_nlink != 1 or metadata.st_size > MAX_TARGET_PAGE_BYTES):
                raise CancellationTargetError("EFFECT_TARGET_INVALID")
            chunks: list[bytes] = []
            size = 0
            while size <= MAX_TARGET_PAGE_BYTES:
                chunk = os.read(descriptor, min(65_536, MAX_TARGET_PAGE_BYTES + 1 - size))
                if not chunk:
                    return b"".join(chunks)
                size += len(chunk)
                chunks.append(chunk)
            raise CancellationTargetError("EFFECT_TARGET_INVALID")
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise CancellationTargetError("EFFECT_TARGET_INVALID") from exc


def verify_cancellation_target(generation: Generation, intent: CorrectionCancellationIntentV1) -> None:
    target = intent.target
    if (
        generation.manifest.provider_instance_id != intent.provider_instance_id
        or generation.generation_id != target.generation_id
        or generation.manifest.generation_digest != target.generation_manifest_digest
        or generation.head != target.vault_head or generation.tree != target.vault_tree
    ):
        raise CancellationTargetError("EFFECT_PRIOR_STALE")
    relative = target.page_id if target.page_id.endswith(".md") else target.page_id + ".md"
    blob_oid = git_run(generation.root, "rev-parse", f"HEAD:{relative}")
    if blob_oid is None or blob_oid.strip() != target.page_blob_oid:
        raise CancellationTargetError("EFFECT_TARGET_INVALID")
    body = _page_bytes(generation.root, relative)
    start, end = target.citation_span_start, target.citation_span_end
    if (
        "sha256:" + hashlib.sha256(body).hexdigest() != target.page_content_digest
        or not 0 <= start < end <= len(body)
        or hashlib.sha256(body[start:end]).hexdigest() != target.content_identity_full
    ):
        raise CancellationTargetError("EFFECT_TARGET_INVALID")
