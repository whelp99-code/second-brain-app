"""Pure rendering bounds shared by request acceptance and remember materialization."""


def remember_lines(content: str) -> tuple[str, ...]:
    lines = tuple(content.replace("[^", "\\[\\^").splitlines())
    records = tuple(line.strip() for line in lines if line.strip())
    if not 1 <= len(records) <= 64 or any(len(line.encode("utf-8")) > 4_096 for line in records):
        raise ValueError("WRITE_REQUEST_INVALID")
    return lines
