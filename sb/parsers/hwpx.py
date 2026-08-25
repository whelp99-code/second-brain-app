"""Constrained defusedxml ZIP/XML HWPX parser. Binary HWP is unsupported."""

from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from typing import Final
from xml.etree.ElementTree import Element, ParseError
from zipfile import BadZipFile, LargeZipFile, ZipFile, ZipInfo

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from sb.parsers import FormatUnsupported, InvalidInput, LimitExceeded

HWPX_MEDIA_TYPE: Final = "application/haansofthwpx"
HWPX_PACKAGE_MIMETYPE: Final = "application/hwp+zip"
OLE_MAGIC: Final = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
HWP_FILE_MAGIC: Final = b"HWP Document File"
MAX_ZIP_MEMBERS: Final = 10_000
MAX_MEMBER_BYTES: Final = 67_108_864
MAX_UNCOMPRESSED_BYTES: Final = 536_870_912
MAX_COMPRESSION_RATIO: Final = 100
MAX_EXPANDED_XML_BYTES: Final = 67_108_864
SECTION_NAME: Final = re.compile(r"^Contents/section(\d+)\.xml$")


def _local_name(tag: str) -> str:
    start = tag.rfind("}")
    if start == -1:
        return tag
    return tag[start + 1 :]


def _is_binary_hwp(payload: bytes) -> bool:
    return payload.startswith((OLE_MAGIC, HWP_FILE_MAGIC))


def _safe_member_name(name: str) -> bool:
    if not name or "\x00" in name:
        return False
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    return not (path.is_absolute() or any(part == ".." for part in path.parts) or ":" in path.parts[0])


def _admit_members(infos: tuple[ZipInfo, ...]) -> None:
    if len(infos) > MAX_ZIP_MEMBERS:
        raise LimitExceeded("hwpx zip member count")
    total = 0
    for info in infos:
        if not _safe_member_name(info.filename):
            raise InvalidInput("hwpx zip member path")
        if info.is_dir():
            continue
        if info.flag_bits & 0x1:
            raise InvalidInput("hwpx encrypted zip member")
        if info.file_size > MAX_MEMBER_BYTES:
            raise LimitExceeded("hwpx zip member size")
        if info.compress_size == 0:
            if info.file_size > 0:
                raise LimitExceeded("hwpx zip stored member")
        elif info.file_size > info.compress_size * MAX_COMPRESSION_RATIO:
            raise LimitExceeded("hwpx zip compression ratio")
        total += info.file_size
        if total > MAX_UNCOMPRESSED_BYTES:
            raise LimitExceeded("hwpx zip uncompressed size")


def _read_member(archive: ZipFile, info: ZipInfo) -> bytes:
    with archive.open(info, "r") as handle:
        data = handle.read(MAX_MEMBER_BYTES + 1)
    if len(data) > MAX_MEMBER_BYTES or len(data) > MAX_EXPANDED_XML_BYTES:
        raise LimitExceeded("hwpx expanded member")
    return data


def _element_local_name(elem: Element) -> str | None:
    tag = elem.tag
    if type(tag) is not str:
        return None
    return _local_name(tag)


def _paragraph_text(paragraph: Element) -> str:
    parts: list[str] = []
    for elem in paragraph.iter():
        if _element_local_name(elem) == "t" and elem.text:
            parts.append(elem.text)
    return "".join(parts)


def _section_text(root: Element) -> str:
    paragraphs: list[str] = []
    for elem in root.iter():
        if _element_local_name(elem) == "p":
            text = _paragraph_text(elem)
            if text:
                paragraphs.append(text)
    return "\n".join(paragraphs)


def _looks_like_hwpx(infos: tuple[ZipInfo, ...], archive: ZipFile) -> bool:
    names = {info.filename for info in infos}
    if any(SECTION_NAME.match(name) for name in names):
        return True
    for info in infos:
        if info.filename != "mimetype" or info.is_dir():
            continue
        payload = _read_member(archive, info)
        return payload.decode("ascii", errors="replace").strip() == HWPX_PACKAGE_MIMETYPE
    return False


def _extract_sections(archive: ZipFile, sections: tuple[tuple[int, ZipInfo], ...]) -> str:
    texts: list[str] = []
    for _index, info in sections:
        payload = _read_member(archive, info)
        try:
            root = ElementTree.fromstring(payload)
        except (DefusedXmlException, ParseError, UnicodeDecodeError) as exc:
            raise InvalidInput("hwpx section xml") from exc
        text = _section_text(root)
        if text:
            texts.append(text)
    return "\n".join(texts)


def _extract(archive: ZipFile) -> str:
    infos = tuple(archive.infolist())
    _admit_members(infos)
    sections = tuple(
        sorted(
            ((int(match.group(1)), info) for info in infos if (match := SECTION_NAME.match(info.filename))),
            key=lambda item: item[0],
        )
    )
    if not sections:
        if _looks_like_hwpx(infos, archive):
            raise InvalidInput("hwpx missing section xml")
        raise FormatUnsupported("hwpx")
    return _extract_sections(archive, sections)


@dataclass(frozen=True, slots=True)
class HwpxDocumentParser:
    """Read-only HWPX extractor. Binary .hwp stays explicit FormatUnsupported."""

    def parse(self, payload: bytes) -> str:
        if _is_binary_hwp(payload):
            raise FormatUnsupported("hwp")
        if not payload:
            raise InvalidInput("empty hwpx payload")
        try:
            with ZipFile(BytesIO(payload)) as archive:
                return _extract(archive)
        except BadZipFile as exc:
            raise InvalidInput("truncated or corrupt hwpx zip") from exc
        except LargeZipFile as exc:
            raise LimitExceeded("hwpx zip") from exc


__all__ = ("HWPX_MEDIA_TYPE", "HwpxDocumentParser")
