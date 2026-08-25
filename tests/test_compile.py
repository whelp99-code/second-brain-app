"""Cited compile engine: PageSpec contract, derivation skip, cap, vault lint."""

from __future__ import annotations

from pathlib import Path

import pytest

from sb.compile import CAPPED_PAGE_ID, CAPPED_STATUS, compile_pages
from sb.config import Config
from sb.contracts import PageSpec, SourceCite, Unit
from sb.llm import FakeLLM
from sb.store.ledger import Ledger
from sb.vault import VaultLintError, init_vault

ORIGIN_PROFILE = "me-wiki:identity/profile.md"
PAGE_PROFILE = "me-wiki-identity-profile"
TITLE_PROFILE = "profile"
HASH_A = "aa" * 32
HASH_B = "bb" * 32
HASH_C = "cc" * 32
SID_A = HASH_A[:8]
SID_B = HASH_B[:8]
SID_C = HASH_C[:8]
ORIGIN_ONE = "me-wiki:a/one.md"
ORIGIN_TWO = "me-wiki:b/two.md"
ORIGIN_THREE = "me-wiki:c/three.md"
BODY_PROFILE = f"이름은 박정민이다.[^{SID_A}]"
EXISTING_SENTINEL = f"EXISTING_BODY_V1.[^{SID_A}]"
MERGED_BODY = f"MERGED.[^{SID_A}][^{SID_B}]"
POISON_SID = "zzzz9999"
POISON_BODY = f"Poison.[^{POISON_SID}]"


class RecordingLLM:
    """Captures prompts. Mutation of calls/prompts is the double's purpose."""

    def __init__(self, response: str) -> None:
        self.calls: int = 0
        self.prompts: list[str] = []
        self._response: str = response

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
        timeout: int = 120,
    ) -> str:
        del system, json_mode, timeout
        self.calls += 1
        self.prompts.append(prompt)
        return self._response


class _HashLedger:
    def last_compiled_hash(self, page_id: str) -> str | None:
        del page_id
        return None


def _config(*, cap: int = 200) -> Config:
    return Config(
        raw={
            "caps": {"max_llm_calls_compile": cap},
            "llm": {"prompt_version": "v1", "model_id": "fake"},
        }
    )


def _unit(unit_id: str, digest: str, span: str, text: str, origin: str) -> Unit:
    return Unit(
        unit_id=unit_id,
        content_hash=digest,
        span=span,
        text=text,
        origin=origin,
    )


def _profile_unit() -> Unit:
    return _unit("u-profile", HASH_A, "0-20", "이름은 박정민이다.", ORIGIN_PROFILE)


def _seed_cas(root: Path, digest: str) -> None:
    dest = root / "raw" / digest[:2] / digest
    _ = dest.parent.mkdir(parents=True, exist_ok=True)
    written = dest.write_bytes(b"blob")
    assert written == len(b"blob")


def test_compile_pages_returns_exact_pagespec_when_units_fixture(tmp_path: Path) -> None:
    unit = _profile_unit()
    fake = FakeLLM([BODY_PROFILE])
    with Ledger(tmp_path) as ledger:
        pages = compile_pages([unit], ledger, fake, _config())

    expected = PageSpec(
        page_id=PAGE_PROFILE,
        title=TITLE_PROFILE,
        body_md=BODY_PROFILE,
        sources=[
            SourceCite(
                sid=SID_A,
                origin=ORIGIN_PROFILE,
                hash=HASH_A,
                spans=["0-20"],
            )
        ],
        status="active",
    )
    assert pages == [expected]
    assert fake.calls == 1


def test_compile_pages_makes_zero_llm_calls_when_called_again_with_same_inputs(
    tmp_path: Path,
) -> None:
    unit = _profile_unit()
    fake = FakeLLM([BODY_PROFILE])
    with Ledger(tmp_path) as ledger:
        first = compile_pages([unit], ledger, fake, _config())
        second = compile_pages([unit], ledger, fake, _config())

    assert first[0].page_id == PAGE_PROFILE
    assert fake.calls == 1
    assert second == []


def test_compile_pages_returns_one_page_and_capped_when_cap_is_one_and_three_pending(
    tmp_path: Path,
) -> None:
    units = [
        _unit("u1", HASH_A, "0-1", "one", ORIGIN_ONE),
        _unit("u2", HASH_B, "0-1", "two", ORIGIN_TWO),
        _unit("u3", HASH_C, "0-1", "three", ORIGIN_THREE),
    ]
    fake = FakeLLM([f"one.[^{SID_A}]", f"two.[^{SID_B}]", f"three.[^{SID_C}]"])
    with Ledger(tmp_path) as ledger:
        pages = compile_pages(units, ledger, fake, _config(cap=1))

    compiled = [page for page in pages if page.status != CAPPED_STATUS]
    markers = [page for page in pages if page.status == CAPPED_STATUS]
    assert fake.calls == 1
    assert len(compiled) == 1
    assert compiled[0].page_id == "me-wiki-a-one"
    assert compiled[0].status == "active"
    assert len(markers) == 1
    assert markers[0].page_id == CAPPED_PAGE_ID
    assert markers[0].status == CAPPED_STATUS


def test_compile_pages_maps_sid_to_first_eight_of_content_hash(tmp_path: Path) -> None:
    units = [
        _unit("u-a", HASH_A, "0-4", "alpha", ORIGIN_PROFILE),
        _unit("u-b", HASH_B, "4-8", "beta", ORIGIN_PROFILE),
    ]
    fake = FakeLLM([f"alpha.[^{SID_A}] beta.[^{SID_B}]"])
    with Ledger(tmp_path) as ledger:
        pages = compile_pages(units, ledger, fake, _config())

    assert len(pages) == 1
    cites = pages[0].sources
    assert [cite.sid for cite in cites] == [SID_A, SID_B]
    assert cites[0].hash == HASH_A
    assert cites[1].hash == HASH_B
    assert cites[0].origin == ORIGIN_PROFILE
    assert cites[1].origin == ORIGIN_PROFILE
    assert cites[0].spans == ["0-4"]
    assert cites[1].spans == ["4-8"]


def test_compile_pages_includes_existing_body_in_prompt_when_recompiling_same_origin(
    tmp_path: Path,
) -> None:
    first_unit = _unit("u1", HASH_A, "0-4", "alpha", ORIGIN_PROFILE)
    second_unit = _unit("u2", HASH_B, "4-8", "beta", ORIGIN_PROFILE)
    recorder = RecordingLLM(MERGED_BODY)
    with Ledger(tmp_path) as ledger:
        first = compile_pages([first_unit], ledger, FakeLLM([EXISTING_SENTINEL]), _config())
        second = compile_pages([first_unit, second_unit], ledger, recorder, _config())

    assert first[0].body_md == EXISTING_SENTINEL
    assert recorder.calls == 1
    assert EXISTING_SENTINEL in recorder.prompts[0]
    assert second_unit.text in recorder.prompts[0]
    assert second[0].body_md == MERGED_BODY


def test_compile_pages_returns_pagespec_and_vault_rejects_when_body_has_unknown_sid(
    tmp_path: Path,
) -> None:
    vault = init_vault(tmp_path)
    _seed_cas(tmp_path, HASH_A)
    fake = FakeLLM([POISON_BODY])
    with Ledger(tmp_path) as ledger:
        pages = compile_pages([_profile_unit()], ledger, fake, _config())

    assert len(pages) == 1
    assert pages[0].body_md == POISON_BODY
    assert pages[0].sources[0].sid == SID_A
    with pytest.raises(VaultLintError) as raised:
        _ = vault.write_pages(pages, "run-poison", _HashLedger())
    assert any("unresolved" in reason and POISON_SID in reason for reason in raised.value.reasons)
