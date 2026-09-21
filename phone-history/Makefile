.PHONY: verify test lint contracts ios-static compile smoke

verify: compile lint contracts test ios-static smoke

compile:
	python3 -m compileall -q server scripts tests

lint:
	python3 -m ruff check server tests scripts

contracts:
	python3 scripts/verify-contracts.py

test:
	python3 -m pytest -q

ios-static:
	python3 scripts/verify-ios-static.py

smoke:
	python3 scripts/smoke-test.py
