import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "transition_units", Path(__file__).resolve().parents[1] / "deploy/check-transition-units.py"
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"ActiveState": "active", "SubState": "waiting"}, "UNIT_NOT_DRAINED"),
        ({"MainPID": "123"}, "UNIT_HAS_PROCESS"),
        ({"ControlPID": "123"}, "UNIT_HAS_PROCESS"),
        ({"Job": "123"}, "UNIT_HAS_PENDING_JOB"),
        ({"LoadState": "not-found"}, "UNIT_NOT_LOADED"),
        ({"ActiveState": "activating"}, "UNIT_NOT_DRAINED"),
    ],
)
def test_rejects_live_or_unverified_unit(changes, reason):
    state = {
        "LoadState": "loaded",
        "ActiveState": "inactive",
        "SubState": "dead",
        "MainPID": "0",
        "ControlPID": "0",
        "Job": "",
    }
    assert reason in module.assess_unit({**state, **changes})


def test_drained_unit_and_empty_response():
    assert (
        module.assess_unit({"LoadState": "loaded", "ActiveState": "inactive", "SubState": "dead"})
        == []
    )
    assert "UNIT_NOT_LOADED" in module.assess_unit({})
