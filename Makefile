.PHONY: install test demo demo-live certificate certificate-check certificate-verify check

install: ; uv sync
test: ; uv run pytest -v
demo: ; uv run python -m contract_eval evaluate --case nda
demo-live: ; uv run --extra live python -m contract_eval evaluate --case all --live
certificate: ; uv run python -m contract_eval certify --case all --out examples
certificate-check: ; uv run python scripts/check_release_certificate.py
certificate-verify: ; uv run python -m contract_eval verify-certificate --certificate examples/release-certificate.json
check: test certificate-check certificate-verify
