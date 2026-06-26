.PHONY: install test demo demo-live check

install: ; uv sync
test: ; uv run pytest -v
demo: ; uv run python -m contract_eval evaluate --case nda
demo-live: ; uv run --extra live python -m contract_eval evaluate --case all --live
check: test
