.PHONY: install test lint smoke doctor endpoints demo agent-doctor

PYTHON ?= .venv/bin/python
TPLINKCTL ?= .venv/bin/tplinkctl

install:
	$(PYTHON) -m pip install .

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests

lint:
	$(PYTHON) -m py_compile tpadmin.py src/tplink_admin/*.py tests/*.py

smoke: lint test
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
