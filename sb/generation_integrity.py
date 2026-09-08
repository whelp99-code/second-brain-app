"""Validate persisted generation identity and its derived file inventory on reads."""
from __future__ import annotations

import hashlib
import os
import stat
import threading
from collections import OrderedDict
from pathlib import Path

from sb.effect_values import (
    JsonObject,
    JsonValue,
    canonical_bytes,
    digest,
    is_json_object,
    strict_loads,
)

_FIELDS = frozenset((
    "schema_version", "generation_id", "generation_digest", "provider_instance_id",
    "provider_release_sha", "parent_generation_id", "head", "tree", "tombstone_sequence",
    "tombstone_set_root", "content_manifest_digest", "ledger_manifest_digest",
    "lexical_manifest_digest", "vector_manifest_digest", "briefing_manifest_digest",
    "file_count", "byte_count", "created_at",
))
_STORES = frozenset(("ledger.db", "search.db", "vectors.db", "briefing-manifest.json"))
type FileIdentity = tuple[int, int, int, int, int, int, int, int]
_CACHE: OrderedDict[FileIdentity, str] = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_LIMIT = 128


class GenerationIntegrityError(ValueError):
    pass


def _identity(info: os.stat_result) -> FileIdentity:
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
        or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
        raise GenerationIntegrityError("unsafe generation file")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
            info.st_mode, info.st_uid, info.st_nlink)


def _read_digest(fd: int) -> str:
    value = hashlib.sha256()
    while block := os.read(fd, 1024 * 1024):
        value.update(block)
    return "sha256:" + value.hexdigest()


def _file_digest(path: Path, expected_bytes: int) -> str:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        identity = _identity(os.fstat(fd))
        if identity[2] != expected_bytes:
            raise GenerationIntegrityError("generation file size mismatch")
        # Immutable readers repeatedly inspect the same files. Cache only content
        # hashes, keyed by kernel identity including ctime; no model/pipeline state.
        with _CACHE_LOCK:
            value = _CACHE.get(identity)
            if value is not None:
                _CACHE.move_to_end(identity)
        if value is None:
            value = _read_digest(fd)
        if _identity(os.fstat(fd)) != identity or _identity(path.lstat()) != identity:
            raise GenerationIntegrityError("generation file changed during validation")
        with _CACHE_LOCK:
            _CACHE[identity] = value
            _CACHE.move_to_end(identity)
            if len(_CACHE) > _CACHE_LIMIT:
                _ = _CACHE.popitem(last=False)
        return value
    finally:
        os.close(fd)


def _read_object(path: Path) -> JsonObject:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = _identity(os.fstat(fd))
        if before[2] > 65_536:
            raise GenerationIntegrityError("generation manifest too large")
        with os.fdopen(os.dup(fd), "rb") as stream:
            value = strict_loads(stream.read(65_537), 65_536)
        if _identity(os.fstat(fd)) != before or _identity(path.lstat()) != before:
            raise GenerationIntegrityError("generation manifest changed during validation")
        if not is_json_object(value):
            raise GenerationIntegrityError("invalid generation manifest")
        return value
    finally:
        os.close(fd)


def _validate_identity(manifest: JsonObject) -> None:
    if frozenset(manifest) != _FIELDS or type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
        raise GenerationIntegrityError("invalid generation schema")
    for key in ("file_count", "byte_count", "tombstone_sequence"):
        value = manifest[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise GenerationIntegrityError("invalid generation count")
    body: dict[str, JsonValue] = {key: value for key, value in manifest.items()
                                  if key not in ("generation_id", "generation_digest")}
    expected = digest("generation", body)
    if manifest["generation_digest"] != expected or manifest["generation_id"] != "sbgen:v1:" + expected[7:]:
        raise GenerationIntegrityError("generation identity digest mismatch")


def load_verified_manifest(root: Path) -> JsonObject:
    """Check self identity, closed inventory/bindings, and all named derived bytes.

    Caller retains the normal generation read pin while using the result. This
    validates corruption against the persisted inventory, not an external signature.
    """
    try:
        manifest = _read_object(root / "generation.json")
        _validate_identity(manifest)
        outer = root.lstat()
        if not stat.S_ISDIR(outer.st_mode) or outer.st_uid != os.getuid() or stat.S_IMODE(outer.st_mode) & 0o077:
            raise GenerationIntegrityError("unsafe generation directory")
        folder = root / ".sb"
        metadata = folder.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise GenerationIntegrityError("unsafe derived directory")
        inventory = _read_object(folder / "derived-manifest.json")
        expected: JsonObject = {
            "schema_version": 1,
            **{key: manifest[key] for key in ("generation_id", "head", "tree",
                "tombstone_sequence", "tombstone_set_root")},
            "logical_manifests": {key: manifest[key + "_manifest_digest"]
                                  for key in ("ledger", "lexical", "vector", "briefing")},
        }
        if set(inventory) != {*expected, "stores"} or canonical_bytes({key: inventory[key] for key in expected}) != canonical_bytes(expected):
            raise GenerationIntegrityError("derived inventory binding mismatch")
        stores = inventory["stores"]
        if not isinstance(stores, list) or len(stores) != len(_STORES):
            raise GenerationIntegrityError("invalid derived inventory")
        seen: set[str] = set()
        for row in stores:
            if not is_json_object(row) or set(row) != {"name", "digest", "bytes"}:
                raise GenerationIntegrityError("invalid derived inventory row")
            name, size, checksum = row["name"], row["bytes"], row["digest"]
            if (not isinstance(name, str) or name not in _STORES or name in seen
                or not isinstance(size, int) or isinstance(size, bool) or size < 0
                or not isinstance(checksum, str)):
                raise GenerationIntegrityError("invalid derived inventory row")
            seen.add(name)
            if _file_digest(folder / name, size) != checksum:
                raise GenerationIntegrityError("derived file digest mismatch")
        return manifest
    except (OSError, ValueError) as exc:
        raise GenerationIntegrityError("GENERATION_SPLIT_BRAIN") from exc
