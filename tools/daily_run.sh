#!/usr/bin/env bash
# daily_run.sh — End-to-end daily runner for Fortify 45-Day Sprint.
#
# Usage:
#   ./tools/daily_run.sh            # Runs full loop (Fetch -> Gate/Score -> Gate A pause -> Customize -> Sync)
#   ./tools/daily_run.sh fetch      # Step 1 only
#   ./tools/daily_run.sh score      # Step 2 only (reads .pipeline/fetched.json)
#   ./tools/daily_run.sh customize  # Step 3 only (customizes approved rows)
#   ./tools/daily_run.sh sync       # Step 4 only (Supabase sync & tracker rebuild)

set -euo pipefail
cd "$(dirname "$0")/.."

STAGE="${1:-all}"

export PATH="/Library/TeX/texbin:/usr/local/bin:$PATH"

case "$STAGE" in
  fetch)
    echo "=== STEP 1: FETCHING POSTINGS ==="
    python3 tools/fetch_jobs.py
    ;;
  score)
    echo "=== STEP 2: GATE 0 (ITAR/VISA) & FIT SCORING ==="
    python3 tools/gate_and_score.py
    ;;
  customize)
    echo "Stage 3 is the customiser subagent, not a script: run /apply-run (or /customise for one role)."
    echo "It writes Job_Applications_Resumes/<today>/ and .pipeline/tailored.md."
    exit 1
    ;;
  sync)
    echo "=== STEP 4: SUPABASE SYNC & TRACKER REBUILD ==="
    python3 tools/log_and_refresh.py "$@"
    ;;
  all)
    echo "============================================="
    echo "   FORTIFY 45-DAY SPRINT — DAILY RUN        "
    echo "============================================="
    echo "=== STEP 1: FETCHING POSTINGS ==="
    python3 tools/fetch_jobs.py
    echo ""
    echo "=== STEP 2: GATE 0 (ITAR/VISA) & FIT SCORING ==="
    python3 tools/gate_and_score.py
    echo ""
    echo "🧑 GATE A: Review .pipeline/ranked.md shortlist."
    echo "Then run /apply-run (customiser subagent) for the rows you approve."
    ;;
  usage)
    python3 tools/check_usage.py
    ;;
  *)
    echo "Unknown stage: $STAGE"
    echo "Usage: ./tools/daily_run.sh [fetch|score|customize|sync|usage|all]"
    exit 1
    ;;
esac
