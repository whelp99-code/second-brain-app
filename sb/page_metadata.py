"""Literal frontmatter fields shared by committed search projections."""
from __future__ import annotations

from typing import ClassVar, Literal, Protocol

from pydantic import BaseModel, ConfigDict
from yaml import BaseLoader, MappingNode, Node, ScalarNode, YAMLError


class _NodeLoader(Protocol):
    """PyYAML's composition lifecycle; construction of values is never used."""

    def get_single_node(self) -> Node | None: ...
    def dispose(self) -> None: ...


class _MappingFields(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True, strict=True, from_attributes=True, arbitrary_types_allowed=True,
    )
    id: Literal["mapping"]
    value: list[tuple[Node, Node]]


class _ScalarField(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True, strict=True, from_attributes=True,
    )
    id: Literal["scalar"]
    value: str


def frontmatter_value(text: str, key: str) -> str:
    return frontmatter_values(text).get(key, "")


def frontmatter_values(text: str) -> dict[str, str]:
    """Decode a page once when several scalar fields are needed."""
    if not text.startswith("---"):
        return {}
    rest = text[3:].lstrip("\n")
    end = rest.find("\n---")
    if end < 0:
        return {}
    return scalar_frontmatter(rest[:end])


def scalar_frontmatter(block: str) -> dict[str, str]:
    # Decode YAML scalar quoting/folding without constructing typed objects.
    # The public contract remains scalar strings; nested source lists stay empty.
    return _read_scalar_fields(BaseLoader(block))


def _read_scalar_fields(loader: _NodeLoader) -> dict[str, str]:
    """Own the composition resource and parse only the fields we consume."""
    try:
        node = loader.get_single_node()
    except YAMLError:
        return {}
    finally:
        loader.dispose()
    if not isinstance(node, MappingNode):
        return {}
    fields = _MappingFields.model_validate(node)
    return {
        _ScalarField.model_validate(key).value: (
            _ScalarField.model_validate(value).value if isinstance(value, ScalarNode) else ""
        )
        for key, value in fields.value
        if isinstance(key, ScalarNode)
    }
