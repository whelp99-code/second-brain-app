"""The real inbox compiler stores unqualified IDs; web search uses wiki/ IDs."""
from pathlib import Path

from pytest import MonkeyPatch

from sb.pipeline import CitedFake
from tests.test_runtime_reliability import managed
from tests.test_web import request, running
from tests.test_web_effect_recovery import payload_for


def test_web_corrects_and_deletes_real_compiled_inbox(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    config = managed(tmp_path)

    def cited(*_args: object) -> CitedFake:
        return CitedFake()

    monkeypatch.setattr("sb.pipeline._llm", cited)
    with running(config) as base:
        assert request(base + "/api/remember", method="POST",
                        payload={"title": "Inbox identity", "content": "original inbox source"})[0] == 201
        status, run = request(base + "/api/run", method="POST", payload={})
        assert status == 200 and isinstance(run, dict) and run["exit_code"] == 0
        _, hits = request(base + "/api/search?q=Cited&kind=wiki")
        assert isinstance(hits, dict)
        rows = hits["results"]
        assert isinstance(rows, list) and rows and isinstance(rows[0], dict)
        page_id = rows[0]["page_id"]
        assert isinstance(page_id, str)
        url = base + "/api/pages/" + page_id
        _, page = request(url)
        payload = payload_for(page, "M13COMPILED corrected source")
        status, result = request(url + "/correct", method="POST", payload=payload)
        assert status == 200, result
        _, corrected = request(url)
        assert isinstance(corrected, dict) and "M13COMPILED" in str(corrected["body"])
        status, result = request(url + "/forget", method="POST",
                                 payload={"receipt": corrected["receipt"]})
        assert status == 200, result
        assert request(base + "/api/search?q=M13COMPILED") == (200, {"results": []})
        assert request(url)[0] == 404
