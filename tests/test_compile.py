"""Cited compile engine: PageSpec contract, derivation skip, cap, vault lint."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from sb.compile import CAPPED_PAGE_ID, CAPPED_STATUS, compile_pages
from sb.config import Config
from sb.contracts import PageSpec, SourceCite, Unit
from sb.llm import FakeLLM
from sb.store import deriv_key
from sb.store.ledger import Ledger
from sb.vault import VaultLintError, init_vault

ORIGIN_PROFILE = "me-wiki:identity/profile.md"
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
ORIGIN_SLASH = "me-wiki:foo/bar.md"
ORIGIN_DASH = "me-wiki-foo:bar.md"
ORIGIN_DIGEST_LEN = 8


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


def _origin_digest(origin: str) -> str:
    return hashlib.sha256(origin.encode("utf-8")).hexdigest()[:ORIGIN_DIGEST_LEN]


def _expected_page_id(origin: str) -> str:
    digest = _origin_digest(origin)
    trimmed = origin.removesuffix(".md")
    chars = [char.lower() if char.isalnum() else "-" for char in trimmed]
    slug = "".join(chars)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return f"{slug.strip('-')}-{digest}"


PAGE_PROFILE = _expected_page_id(ORIGIN_PROFILE)


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
        prompt_version="v1",
        model_id="fake",
        derivation_key=deriv_key((unit.unit_id,), "compile", "v1", "fake"),
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
    assert compiled[0].page_id == _expected_page_id(ORIGIN_ONE)
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


def test_compile_pages_returns_two_pages_when_slugified_origins_collide(
    tmp_path: Path,
) -> None:
    units = [
        _unit("u-slash", HASH_A, "0-1", "slash", ORIGIN_SLASH),
        _unit("u-dash", HASH_B, "0-1", "dash", ORIGIN_DASH),
    ]
    fake = FakeLLM([f"slash.[^{SID_A}]", f"dash.[^{SID_B}]"])
    with Ledger(tmp_path) as ledger:
        pages = compile_pages(units, ledger, fake, _config())

    assert len(pages) == 2
    ids = {page.page_id for page in pages}
    assert len(ids) == 2
    by_origin = {page.sources[0].origin: page for page in pages}
    assert by_origin[ORIGIN_SLASH].page_id == _expected_page_id(ORIGIN_SLASH)
    assert by_origin[ORIGIN_DASH].page_id == _expected_page_id(ORIGIN_DASH)
    assert _origin_digest(ORIGIN_SLASH) in by_origin[ORIGIN_SLASH].page_id
    assert _origin_digest(ORIGIN_DASH) in by_origin[ORIGIN_DASH].page_id
    assert fake.calls == 2


def test_compile_pages_page_ids_are_stable_when_unit_order_changes(tmp_path: Path) -> None:
    unit_slash = _unit("u-slash", HASH_A, "0-1", "slash", ORIGIN_SLASH)
    unit_dash = _unit("u-dash", HASH_B, "0-1", "dash", ORIGIN_DASH)
    with Ledger(tmp_path / "fwd") as ledger:
        forward = compile_pages(
            [unit_slash, unit_dash],
            ledger,
            FakeLLM([f"slash.[^{SID_A}]", f"dash.[^{SID_B}]"]),
            _config(),
        )
    with Ledger(tmp_path / "rev") as ledger:
        reverse = compile_pages(
            [unit_dash, unit_slash],
            ledger,
            FakeLLM([f"slash.[^{SID_A}]", f"dash.[^{SID_B}]"]),
            _config(),
        )

    assert {page.page_id for page in forward} == {page.page_id for page in reverse}
    assert len(forward) == 2
    assert len(reverse) == 2


def test_compile_pages_page_id_matches_solo_when_batched_with_collider(
    tmp_path: Path,
) -> None:
    unit_slash = _unit("u-slash", HASH_A, "0-1", "slash", ORIGIN_SLASH)
    unit_dash = _unit("u-dash", HASH_B, "0-1", "dash", ORIGIN_DASH)
    with Ledger(tmp_path / "solo") as ledger:
        solo = compile_pages([unit_slash], ledger, FakeLLM([f"slash.[^{SID_A}]"]), _config())
    with Ledger(tmp_path / "batch") as ledger:
        batch = compile_pages(
            [unit_slash, unit_dash],
            ledger,
            FakeLLM([f"slash.[^{SID_A}]", f"dash.[^{SID_B}]"]),
            _config(),
        )

    assert len(solo) == 1
    assert len(batch) == 2
    batched_slash = next(page for page in batch if page.sources[0].origin == ORIGIN_SLASH)
    assert solo[0].page_id == batched_slash.page_id
    assert solo[0].page_id == _expected_page_id(ORIGIN_SLASH)
