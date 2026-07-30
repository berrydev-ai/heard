#!/usr/bin/env bash
# Fork-only guard (PreToolUse / Bash).
#
# This checkout is a fork of heardlabs/heard and nothing here is ever
# contributed upstream. See the "This is a fork" section in CLAUDE.md.
#
# Denies:
#   1. Any command naming `heardlabs` (gh --repo heardlabs/heard, a push to
#      a heardlabs URL, gh repo set-default heardlabs/heard, ...).
#   2. `git push` to any remote that isn't `origin`.
#
# Explicitly ALLOWED:
#   - force pushes to origin (`git push --force origin main`) — deliberate,
#     this is Eric's own fork.
#
# Reads the PreToolUse payload on stdin, prints a deny decision as JSON, and
# always exits 0 (the decision travels in the JSON, not the exit code).

set -uo pipefail

cmd=$(jq -r '.tool_input.command // empty' 2>/dev/null) || exit 0
[ -n "$cmd" ] || exit 0

deny() {
  # jq -n builds the JSON so the reason is escaped correctly.
  jq -nc --arg r "$1" \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
  exit 0
}

# 1. Anything naming the upstream org.
if printf '%s' "$cmd" | grep -qiE 'heardlabs'; then
  deny "Fork-only rule (CLAUDE.md): this repo never pushes, PRs, or comments to heardlabs/heard. Target berrydev-ai/heard instead, or ask Eric before proceeding."
fi

# 2. git push to a remote that isn't origin.
# Pull out the first `git push ...` clause, drop everything from the next
# shell separator on, then take the first argument that isn't a flag.
push_clause=$(printf '%s' "$cmd" | grep -oE 'git[[:space:]]+push([[:space:]]+[^;&|]*)?' | head -1)
if [ -n "$push_clause" ]; then
  remote=$(printf '%s' "$push_clause" \
    | sed -E 's/^git[[:space:]]+push//' \
    | tr ' \t' '\n\n' \
    | grep -vE '^(-.*)?$' \
    | head -1)
  if [ -n "$remote" ] && [ "$remote" != "origin" ]; then
    deny "Fork-only rule (CLAUDE.md): push only to 'origin' (berrydev-ai/heard). Refusing a push to '$remote'. Force pushes to origin are allowed."
  fi
fi

exit 0
