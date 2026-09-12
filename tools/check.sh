#!/usr/bin/env bash
# The whole offline test suite in one command. ~10 seconds, no network, no Apify.
# Runs from the pre-commit hook and from .github/workflows/check.yml.
# Every self-test exits non-zero on failure, so `set -e` is the assertion.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
python3 -m py_compile tools/*.py tools/lib/*.py
python3 tools/lib/profile_config.py
python3 tools/lib/ledger.py
python3 tools/fetch_jobs.py --self-test
python3 tools/keyword_engine.py --self-test
python3 tools/keyword_engine.py --audit
python3 tools/gate_and_score.py --self-test
python3 tools/resolve_track.py --self-test
python3 tools/log_and_refresh.py --self-test
python3 refresh.py --selftest
node tools/ats_scan.mjs --self-test
echo "check.sh: all green"
