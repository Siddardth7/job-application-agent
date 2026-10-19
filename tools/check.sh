#!/usr/bin/env bash
# The whole offline test suite in one command. No network, no Apify.
# Every self-test exits non-zero on failure, so `set -e` is the assertion.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
python3 -m py_compile tools/*.py tools/lib/*.py
python3 tools/lib/profile_config.py
python3 tools/lib/ledger.py
python3 tools/fetch_jobs.py --self-test
python3 tools/gates.py --self-test
python3 tools/triage.py --self-test
python3 tools/log_apps.py --self-test
node tools/ats_scan.mjs --self-test
echo "check.sh: all green"
