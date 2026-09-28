"""Bounded Life source parsing; no persistence or network I/O."""

from __future__ import annotations

import math

from sb.effect_values import JsonInput
from sb.life_contracts import LifeInputError


def number(value: JsonInput, lower: float, upper: float) -> float:
    if (
        (type(value) is not int and type(value) is not float)
        or not math.isfinite(value)
        or not lower <= value <= upper
    ):
        raise LifeInputError("LIFE_SENSOR_NUMBER_INVALID")
    return float(value)
