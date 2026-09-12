#!/usr/bin/env bash
# Regenerate the standalone tracker page (job_tracker.html) and, with --fetch, sync the
# tracker's drop-notes into learning_log.md. The page itself reads Supabase live on every
# open, so the daily run never needs to rebuild it — only write rows to Supabase.
#
#   ./refresh.sh            # write ./job_tracker.html (bookmark it)
#   ./refresh.sh --fetch    # + sync drop reviews (needs SUPABASE_KEY in .env)
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a
python3 refresh.py "$@"
