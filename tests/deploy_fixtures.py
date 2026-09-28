"""Load standalone deployment scripts for typed in-process fault-injection tests."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType


def load_deploy(name: str) -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "deploy" / name
    spec = spec_from_file_location(path.stem.replace("-", "_"), path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
