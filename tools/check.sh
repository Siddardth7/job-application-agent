#!/usr/bin/env bash
# The whole offline test suite in one command. ~10 seconds, no network, no Apify.
# Runs from the pre-commit hook and from .github/workflows/check.yml.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
python3 -m py_compile tools/*.py tools/lib/*.py
python3 tools/lib/profile_config.py
python3 tools/lib/ledger.py
python3 tools/fetch_jobs.py --self-test | tail -1 | grep -q "ALL PASS"
python3 tools/keyword_engine.py --self-test | tail -1 | grep -q "ALL PASS"
python3 tools/keyword_engine.py --audit | tail -1 | grep -q "AUDIT OK"
python3 tools/gate_and_score.py --self-test | tail -1 | grep -q "ALL PASS"
node tools/ats_scan.mjs --self-test
echo "check.sh: all green"
