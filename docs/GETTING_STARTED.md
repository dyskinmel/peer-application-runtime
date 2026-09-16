# Getting started

## Reference/local path

Requirements: Python 3 and a normal source checkout. No production credentials are required.

```bash
python3 tools/harness.py validate
python3 examples/store_demo.py
python3 tools/check_wire.py
```

Other focused examples are under `examples/`. Store and crypto reference checks are available through `tools/check_store.py` and `tools/check_crypto.py`; their PASS status is local/reference evidence, not native qualification.

## Native path

A native-capable environment needs Rust stable, Cargo, and the additional dependencies reported by the native preflight.

```bash
python3 tools/harness.py native-resume
```

Read the machine-readable result before starting a native lane. G0-CRYPTO must not be auto-promoted by downloading or swapping a provider without the explicit security decision/review required by the repository contracts.

## Development workflow

Use a focused change loop:

```text
implement -> focused test -> S0 -> impact analysis -> relevant S1 -> commit/checkpoint
```

Reserve broader S2/S3 campaigns for appropriate milestones. Do not use a timeout, missing tool, or stale receipt as a substitute for a successful verification.
