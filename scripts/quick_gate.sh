#!/usr/bin/env bash
# Quick gate for the session verification hook, which looks for this exact path.
# Unit tests only: they finish in about a second and write nothing outside ignored paths,
# which the hook requires. `make check` remains the release gate.
set -euo pipefail
cd "$(dirname "$0")/.."
exec make test
