#!/usr/bin/env bash
# One-line artifact refresh for the Job Search Tracker.
# Regenerates the Cowork artifact index.html (auto-deploys) from Supabase.
#
# Usage:
#   ./refresh.sh --fetch     # pull live from Supabase REST (needs SUPABASE_KEY in env or .env)
#   ./refresh.sh             # rebuild from ./tracker_data.json (produced during the daily run)
#
# Put SUPABASE_KEY (service_role recommended) in a local .env next to this file; it is sourced
# automatically and never committed. Example .env:
#   SUPABASE_KEY=sb_secret_xxx   # or the service_role JWT
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a
python3 refresh.py "$@"
