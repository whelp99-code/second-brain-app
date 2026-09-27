"""Decode external Life JSON using a closed recursive value contract."""

from __future__ import annotations

import json
from collections.abc import Callable

from sb.effect_values import JsonInput, JsonValue

type LifePayload = dict[str, JsonInput]

# With no custom hooks, json.loads already produces exactly the JsonValue union.
# Leave domain validation to consumers; revalidating this recursive union changes
# decoder depth limits and can amplify one bad field into a huge diagnostic.
decode_json: Callable[[bytes | str], JsonValue] = json.loads
