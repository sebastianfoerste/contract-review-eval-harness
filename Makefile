.PHONY: install test demo demo-live certificate certificate-check certificate-verify anchor-check robustness robustness-check check

install: ; uv sync
test: ; uv run pytest -v
demo: ; uv run python -m contract_eval evaluate --case nda
demo-live: ; uv run --extra live python -m contract_eval evaluate --case all --live
certificate: ; uv run python -m contract_eval certify --case all --out examples
certificate-check: ; uv run python scripts/check_release_certificate.py
anchor-check: ; uv run python scripts/check_clause_anchors.py
certificate-verify: ; uv run python -m contract_eval verify-certificate --certificate examples/release-certificate.json
robustness: ; uv run python -m contract_eval robustness --campaign robustness/campaign.v1.json --out examples
robustness-check:
	uv run python -m contract_eval verify-robustness --report examples/adversarial-robustness-report.json --campaign robustness/campaign.v1.json
	uv run python scripts/check_robustness_report.py
check: test anchor-check certificate-check certificate-verify robustness-check
