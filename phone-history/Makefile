PYTHON ?= python3

.PHONY: verify test lint contracts ios-static compile smoke

# One authoritative pre-device gate; this never claims native/device acceptance.
verify:
	$(PYTHON) scripts/run_predevice_gate.py

compile:
	$(PYTHON) -m compileall -q server scripts tests

lint:
	$(PYTHON) -m ruff format --check server tests scripts
	$(PYTHON) -m ruff check server tests scripts

contracts:
	$(PYTHON) scripts/generate_ios_contract.py
	$(PYTHON) scripts/generate_ios_api_paths.py

test:
	$(PYTHON) -m pytest -q

ios-static:
	$(PYTHON) scripts/verify_ios_static.py

smoke:
	$(PYTHON) -m pytest -q tests/test_api.py tests/test_second_brain_sink.py
