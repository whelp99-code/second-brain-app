"""Literal frontmatter fields shared by committed search projections."""
from __future__ import annotations

from typing import cast

from yaml import BaseLoader, MappingNode, ScalarNode, YAMLError


def frontmatter_value(text: str, key: str) -> str:
    if not text.startswith("---"):
        return ""
    rest = text[3:].lstrip("\n")
    end = rest.find("\n---")
    if end < 0:
        return ""
    return scalar_frontmatter(rest[:end]).get(key, "")


def scalar_frontmatter(block: str) -> dict[str, str]:
    # Decode YAML scalar quoting/folding without constructing typed objects.
    # The public contract remains scalar strings; nested source lists stay empty.
    loader = BaseLoader(block)
    try:
        node = cast(object, loader.get_single_node())
    except YAMLError:
        return {}
    finally:
        loader.dispose()
    if not isinstance(node, MappingNode):
        return {}
    return {
        cast(str, key.value): cast(str, value.value) if isinstance(value, ScalarNode) else ""
        for key, value in cast(list[tuple[object, object]], node.value)
        if isinstance(key, ScalarNode)
    }
