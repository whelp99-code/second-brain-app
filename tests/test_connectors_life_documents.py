from email.message import EmailMessage
from pathlib import Path

import pytest

from sb.config import Config
from sb.connectors.life_documents import create
from sb.web_push import PushServerRefused, listen, notification_request


def _eml(subject: str, body: str) -> bytes:
    message = EmailMessage()
    message["Subject"] = subject
    message.set_content(body)
    return message.as_bytes()


def _config(root: Path) -> Config:
    return Config(
        raw={
            "vault_root": str(root / "vault"),
            "sources": [{"id": "life", "adapter": "life-documents", "root": str(root / "exports")}],
        }
    )


def test_export_scan_keeps_originals_and_reads_mail_kakao_and_calls(tmp_path: Path) -> None:
    exports = tmp_path / "exports"
    exports.mkdir()
    eml = exports / "note.eml"
    kakao = exports / "chat.kakao.txt"
    call = exports / "today.call.vtt"
    audio = exports / "voice.m4a"
    _ = eml.write_bytes(_eml("계약", "수요일에 발송한다. password=secret"))
    _ = kakao.write_text("카카오 내보내기\n회의는 내일", encoding="utf-8")
    _ = call.write_text("WEBVTT\n\n00:00.000 --> 00:01.000\n통화 내용", encoding="utf-8")
    _ = audio.write_bytes(b"not-a-real-audio")
    before = {path.name: path.read_bytes() for path in exports.iterdir()}
    adapter = create(_config(tmp_path))
    items = list(adapter.scan(None))
    after = {path.name: path.read_bytes() for path in exports.iterdir()}
    by_name = {item[0].source_uri: item for item in items}
    assert before == after
    assert "수요일에 발송한다" in by_name["note.eml"][1].decode()
    assert "회의는 내일" in by_name["chat.kakao.txt"][1].decode()
    assert "통화 내용" in by_name["today.call.vtt"][1].decode()
    assert "voice.m4a" not in by_name
    assert audio.read_bytes() == b"not-a-real-audio"
    assert (
        "password=secret" in eml.read_text(encoding="utf-8", errors="replace")
        or b"password=secret" in eml.read_bytes()
    )


def test_missing_export_root_does_not_raise(tmp_path: Path) -> None:
    adapter = create(_config(tmp_path))
    items = list(adapter.scan(None))
    assert items[0][2].get("skip_reason") == "absent-root"


def test_web_push_builds_a_request_and_refuses_to_listen() -> None:
    payload = notification_request("https://push.example/send", "브리핑", "새 추천")
    assert payload["endpoint"].startswith("https://")
    with pytest.raises(ValueError):
        _ = notification_request("http://push.example/send", "브리핑", "새 추천")
    with pytest.raises(PushServerRefused, match="NO_PUSH_SERVER"):
        listen()
