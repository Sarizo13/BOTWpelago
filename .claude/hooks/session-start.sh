#!/bin/bash
# SessionStart hook for Claude Code on the web.
# Installs the test/lint tooling + runtime dependency so `pytest` and `ruff`
# work out of the box in a fresh web session. Synchronous + idempotent.
set -euo pipefail

# Only run inside the Claude Code remote (web) environment.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"

# Runtime dep (websockets) + test/lint tooling (pytest, ruff).
# The tests import BotWClient.save_parser (stdlib only) and read JSON data;
# ruff lints worlds/botw + tests. None of that needs oead.
python3 -m pip install --quiet --disable-pip-version-check -r requirements.txt pytest ruff

# oead is only used by the offline extraction scripts in tools/ (extract_*.py).
# It is a heavy native binding — install best-effort, never fail the session for it.
python3 -m pip install --quiet --disable-pip-version-check oead \
  || echo "note: oead skipped (only needed for tools/extract_*.py)"

echo "session-start hook: tooling ready (pytest, ruff, websockets)."
