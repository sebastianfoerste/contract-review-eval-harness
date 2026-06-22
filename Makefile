.PHONY: install test demo demo-live check

install: ; uv sync
test: ; uv run pytest -v
demo: ; uv run python -m contract_eval evaluate --case nda
demo-live: ; uv run python -m contract_eval evaluate --case nda --live
check: test
