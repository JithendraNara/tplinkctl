.PHONY: install test lint contract docs smoke doctor endpoints demo agent-doctor

PYTHON ?= .venv/bin/python
TPLINKCTL ?= .venv/bin/tplinkctl

install:
	$(PYTHON) -m pip install '.[test]'

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests

lint:
	$(PYTHON) -m py_compile tpadmin.py src/tplink_admin/*.py tests/*.py

contract:
	PYTHONPATH=src $(PYTHON) -m tplink_admin.openapi --check docs/openapi.json
	PYTHONPATH=src $(PYTHON) -m tplink_admin.clidoc --check docs/commands.md
	$(PYTHON) scripts/forge_generate.py validate --spec docs/openapi.json
	$(PYTHON) scripts/forge_test.py

docs:
	PYTHONPATH=src $(PYTHON) -m tplink_admin.openapi > docs/openapi.json
	PYTHONPATH=src $(PYTHON) -m tplink_admin.clidoc > docs/commands.md

smoke: lint test contract
	$(TPLINKCTL) --version
	$(TPLINKCTL) --json routes --bundle-dir examples/bundles --name internet
	$(TPLINKCTL) --json endpoints --bundle-dir examples/bundles --form network

doctor:
	$(TPLINKCTL) --json doctor

endpoints:
	$(TPLINKCTL) --json endpoints

demo:
	PYTHONPATH=src $(PYTHON) -m tplink_admin.cli --json demo

agent-doctor:
	PYTHONPATH=src $(PYTHON) scripts/agent_doctor.py
