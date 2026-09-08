"""The optional model process must fail through the existing lexical fallback contract."""
from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import pytest

from sb import embeddings
from sb.embeddings import EmbeddingUnavailable, ModelIdentity

IDENTITY = ModelIdentity("fixture/model", "fixture-revision", 1024)


def encoder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> embeddings.Encoder:
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.setenv("SB_EMBED_MODEL", IDENTITY.model_id)
    monkeypatch.setenv("SB_EMBED_REVISION", IDENTITY.revision)
    (tmp_path / "hf/hub/models--fixture--model/snapshots" / IDENTITY.revision).mkdir(parents=True)
    return embeddings.resolve_encoder()


def test_partial_cache_never_downloads_during_encoding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model = encoder(tmp_path, monkeypatch)
    # A real child imports this stand-in and verifies the constructor boundary.
    _ = (tmp_path / "sentence_transformers.py").write_text(
        "class SentenceTransformer:\n"
        + " def __init__(self, name, *, revision, local_files_only=False):\n"
        + "  assert local_files_only, 'encoding attempted online model resolution'\n"
        + "  assert name == 'fixture/model' and revision == 'fixture-revision'\n"
        + " def encode(self, texts, *, normalize_embeddings):\n"
        + "  assert normalize_embeddings\n"
        + "  return [[1.0] + [0.0] * 1023 for text in texts]\n"
    )
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    assert model.encode(("fixture text",)) == ((1.0,) + (0.0,) * 1023,)


def test_malformed_model_output_is_embedding_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model = encoder(tmp_path, monkeypatch)
    monkeypatch.setattr(embeddings, "_ENCODE_SCRIPT", "print('unexpected model diagnostic')")
    with pytest.raises(EmbeddingUnavailable, match="invalid embedding process output"):
        _ = model.encode(("fixture text",))


@pytest.mark.parametrize("failure", ["timeout", "launch"])
def test_process_failures_have_a_finite_deadline_and_normalized_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    model = encoder(tmp_path, monkeypatch)

    def run(args: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert 0 < cast(float, kwargs.get("timeout", 0)) <= 60
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args, cast(float, kwargs["timeout"]))
        raise OSError("fixture executable unavailable")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(EmbeddingUnavailable):
        _ = model.encode(("fixture text",))
