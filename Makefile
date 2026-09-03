.PHONY: install test demo demo-live certificate certificate-check certificate-verify anchor-check gold-v2-check evidence-check adjudication-check annotation-pack annotation-bundle migrate-gold-v2 capture-check replay-check live-run-report live-run-check robustness robustness-check check

install: ; uv sync
test: ; uv run pytest -v
demo: ; uv run python -m contract_eval evaluate --case nda
demo-live: ; uv run --extra live python -m contract_eval evaluate --case all --live
certificate: ; uv run python -m contract_eval certify --case all --out examples
certificate-check: ; uv run python scripts/check_release_certificate.py
anchor-check: ; uv run python scripts/check_clause_anchors.py
capture-check: ; uv run pytest tests/test_capture.py -q
replay-check: ; uv run pytest tests/test_replay.py -q
live-run-report: ; uv run python scripts/generate_live_run_report.py
live-run-check: ; uv run python scripts/check_live_run_report.py
gold-v2-check: ; uv run python scripts/check_gold_v2.py
evidence-check: ; uv run pytest tests/test_evidence_binding.py tests/test_policy_v3.py -q
adjudication-check: ; uv run pytest tests/test_adjudication.py -q
annotation-pack: ; uv run python scripts/build_annotation_pack.py
annotation-bundle: ; uv run python scripts/export_annotation_bundle.py
migrate-gold-v2: ; uv run python scripts/migrate_gold_to_v2.py
certificate-verify: ; uv run python -m contract_eval verify-certificate --certificate examples/release-certificate.json
robustness: ; uv run python -m contract_eval robustness --campaign robustness/campaign.v1.json --out examples
robustness-check:
	uv run python -m contract_eval verify-robustness --report examples/adversarial-robustness-report.json --campaign robustness/campaign.v1.json
	uv run python scripts/check_robustness_report.py
check: test anchor-check gold-v2-check evidence-check adjudication-check capture-check replay-check live-run-check certificate-check certificate-verify robustness-check
