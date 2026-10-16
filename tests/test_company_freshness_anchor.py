from __future__ import annotations

from pathlib import Path

import pytest

from sb.company_freshness_anchor import (
    NV_HANDLE,
    AnchorRejected,
    nv_public_is_extend_only,
    parse_nvreadpublic,
    tpm_nvextend_argv,
    tpm_nvread_argv,
    tpm_nvreadpublic_argv,
)

_PUBLIC = """
0x01804F43:
  hash algorithm:
    friendly: sha256
    value: 0xB
  attributes:
    friendly: nt=extend|policydelete|written|ownerread
    value: 0x200
  size: 32
  name: abcd
"""


def test_extend_only_gate_rejects_plain_write() -> None:
    assert nv_public_is_extend_only(frozenset({"nt=extend", "policydelete", "written"}))
    assert not nv_public_is_extend_only(frozenset({"nt=ordinary", "policydelete", "written"}))
    assert not nv_public_is_extend_only(frozenset({"nt=extend", "policydelete"}))


def test_tpm_argv_matches_man_pages_and_is_not_executed(tmp_path: Path) -> None:
    output = tmp_path / "nv.bin"
    assert tpm_nvextend_argv(NV_HANDLE) == ["tpm2_nvextend", "-C", "o", "-i-", NV_HANDLE]
    assert tpm_nvread_argv(NV_HANDLE, output) == [
        "tpm2_nvread",
        "-C",
        "o",
        "-o",
        str(output),
        "-s",
        "32",
        NV_HANDLE,
    ]
    assert tpm_nvreadpublic_argv() == ["tpm2_nvreadpublic"]
    parsed = parse_nvreadpublic(_PUBLIC)
    assert parsed["name"] == "abcd"
    with pytest.raises(AnchorRejected):
        _ = parse_nvreadpublic("0x1:\n  size: 32\n")
