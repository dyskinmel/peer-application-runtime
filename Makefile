PYTHON ?= python3
.PHONY: doctor validate test verify

doctor:
	$(PYTHON) tools/harness.py doctor
validate:
	$(PYTHON) tools/harness.py validate
test:
	$(PYTHON) tools/test_runner.py
verify:
	$(PYTHON) examples/h0_workflow.py

.PHONY: wire verify-wire
wire:
	$(PYTHON) tools/check_wire.py
verify-wire:
	$(PYTHON) examples/wire_workflow.py

.PHONY: store crypto verify-crypto
store:
	$(PYTHON) tools/check_store.py
crypto:
	$(PYTHON) tools/check_crypto.py
verify-crypto:
	$(PYTHON) examples/crypto_workflow.py --include-wire --include-store
