"""Scalar field parsers for Life commands and persisted workflow bodies."""

from sb.config import TomlValue
from sb.effect_values import JsonInput
from sb.life_contracts import LifeInputError


def string(value: JsonInput | TomlValue, code: str = "LIFE_RECORD_CORRUPT") -> str:
    if not isinstance(value, str):
        raise LifeInputError(code)
    return value


def integer(value: JsonInput | TomlValue, code: str = "LIFE_INPUT_INVALID") -> int:
    if type(value) is not int:
        raise LifeInputError(code)
    return value


def boolean(value: JsonInput | TomlValue, code: str = "LIFE_INPUT_INVALID") -> bool:
    if type(value) is not bool:
        raise LifeInputError(code)
    return value


def number(value: JsonInput, code: str = "LIFE_RECORD_CORRUPT") -> float | int:
    if type(value) is not int and type(value) is not float:
        raise LifeInputError(code)
    return value
