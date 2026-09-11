#!/usr/bin/env bash
# Pre-commit PII guard. Refuses the commit if any STAGED file contains personal
# identifiers. Patterns live in .pii_patterns (gitignored — it is itself PII).
# Install:  ln -sf ../../tools/hooks/pii_guard.sh .git/hooks/pre-commit
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
PATTERNS="$ROOT/.pii_patterns"
[ -f "$PATTERNS" ] || { echo "pii_guard: no .pii_patterns file, refusing to commit blind" >&2; exit 1; }
status=0
while IFS= read -r f; do
  [ -f "$ROOT/$f" ] || continue
  if hits=$(git show ":$f" | grep -nEi -f "$PATTERNS" 2>/dev/null); then
    echo "pii_guard: BLOCKED  $f" >&2
    echo "$hits" | head -3 | sed 's/^/    /' | cut -c1-120 >&2
    status=1
  fi
done < <(git diff --cached --name-only --diff-filter=ACM)
[ $status -eq 0 ] || echo "pii_guard: commit refused. Move personal data to a gitignored file or a *.template.* copy." >&2
exit $status
