#!/usr/bin/env bash
# The checks a change passes before it is pushed; .githooks/pre-push runs `fast` on every pushed commit.
#   fast: the tests of file size and of the function limits, ruff's and complexipy's, the lists that only shrink
#         included. Seconds, without the network or a database.
set -u
cd "$(dirname "$0")/.." || exit 1
case "${1:-}" in
  fast) ;;
  *)
    echo "usage: scripts/checks.sh fast" >&2
    exit 2
    ;;
esac
exec uv run --no-sync pytest -q --tb=short tests/test_file_size.py tests/test_function_limits.py
