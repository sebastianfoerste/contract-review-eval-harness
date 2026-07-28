.PHONY: install test demo demo-live certificate certificate-check check

install: ; uv sync
test: ; uv run pytest -v
demo: ; uv run python -m contract_eval evaluate --case nda
demo-live: ; uv run --extra live python -m contract_eval evaluate --case all --live
certificate: ; uv run python -m contract_eval certify --case all --out examples
certificate-check: ; uv run python scripts/check_release_certificate.py
check: test certificate-check
