PYTHON ?= python3

.PHONY: safety-check architecture-check docs-check contracts-check test-g0 verify-g0 status

safety-check:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/safety_scan.py --root .

architecture-check:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/architecture_guard.py --root .

docs-check:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.validate_docs --root .

contracts-check:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.validate_contracts --root .

test-g0:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests -p 'test_*.py'

verify-g0: safety-check architecture-check docs-check contracts-check test-g0

status:
	git status --short --branch
