#!/usr/bin/env bash
# Pre-commit: PII guard first, then the offline test suite.
# Install:  ln -sf ../../tools/hooks/pre-commit.sh .git/hooks/pre-commit
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
"$ROOT/tools/hooks/pii_guard.sh"
"$ROOT/tools/check.sh"
