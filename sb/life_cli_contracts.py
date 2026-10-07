"""Concrete argument and callback boundaries for injected Life CLI operations."""

from collections.abc import Mapping, Sequence
from typing import Protocol

from typing_extensions import TypedDict

from sb.config import Config
from sb.effect_values import JsonInput
from sb.life_json import LifePayload


class LifeArguments(TypedDict):
    life_command: str
    source: list[str]
    input: str | None
    data: str | None
    raw_file: str | None
    format: str
    day: str | None
    slot: str | None
    query: str | None
    as_of: str | None
    send: bool


class LifeRunOutcome(Protocol):
    @property
    def already_running(self) -> bool: ...
    @property
    def exit_code(self) -> int: ...
    @property
    def failure(self) -> str | None: ...
    @property
    def status(self) -> str: ...
    @property
    def run_id(self) -> str: ...
    @property
    def written(self) -> int: ...
    @property
    def errors(self) -> int: ...


class Workflow(Protocol):
    def __call__(
        self,
        config: Config,
        command: str,
        data: Mapping[str, JsonInput],
        *,
        source_ids: tuple[str, ...],
        scopes: tuple[str, ...],
    ) -> tuple[LifeRunOutcome, LifePayload]: ...


class Importer(Protocol):
    def __call__(
        self, config: Config, source_id: str, kind: str, raw: bytes, *, filename: str
    ) -> tuple[LifeRunOutcome, LifePayload]: ...


class Ingester(Protocol):
    def __call__(self, config: Config, sources: Sequence[str] | None) -> LifeRunOutcome: ...


class Maintainer(Protocol):
    def __call__(
        self, config: Config, *, source_ids: tuple[str, ...], scopes: tuple[str, ...]
    ) -> tuple[LifeRunOutcome, LifePayload]: ...


class Callbacks(TypedDict):
    workflow: Workflow
    importer: Importer
    ingest: Ingester
    maintainer: Maintainer
