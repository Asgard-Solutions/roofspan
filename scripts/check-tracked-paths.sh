#!/usr/bin/env bash
# Guard against Windows-incompatible tracked paths.
# Fails if any git-tracked file name contains control characters (0x00-0x1f)
# or characters illegal on Windows (< > : " | ? *), which break Windows checkouts.
set -euo pipefail

bad=$(git ls-files -z | grep -zaP '[\x00-\x1f<>:"|?*]' | tr '\0' '\n' | cat -v || true)

if [ -n "$bad" ]; then
  echo "ERROR: The following tracked paths contain control characters or Windows-illegal characters:" >&2
  echo "$bad" >&2
  echo "" >&2
  echo "These break 'git checkout' on Windows. Remove them with:" >&2
  echo "  git ls-files -z | grep -zaP '[\\x00-\\x1f<>:\"|?*]' > /tmp/bad.nul" >&2
  echo "  git rm --cached --pathspec-from-file=/tmp/bad.nul --pathspec-file-nul" >&2
  exit 1
fi

echo "OK: no Windows-incompatible tracked paths found."
