"""Pure rendering of one correction into individually cited statements."""

import re

_ENDING = re.compile(r"(\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029])$")
_MARKER = re.compile(rb"[ \t]*\[\^([0-9a-f]{8,64})\]")


def correction_marker(suffix: bytes) -> str | None:
    """Only inherit the actual citation immediately following the target span."""
    match = _MARKER.match(suffix)
    return match.group(1).decode("ascii") if match is not None else None


def render_correction(content: str, sid: str | None) -> str:
    """The existing final citation remains outside the replaced span."""
    escaped = content.replace("[^", "\\[\\^")
    if sid is None:
        return escaped
    lines = escaped.splitlines(keepends=True)
    result: list[str] = []
    for index, line in enumerate(lines):
        ending = _ENDING.search(line)
        if index < len(lines) - 1 and ending is not None and line[:ending.start()].strip():
            result.append(line[:ending.start()] + f"[^{sid}]" + ending.group())
        else:
            result.append(line)
    return "".join(result)
