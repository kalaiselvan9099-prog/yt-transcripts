#!/usr/bin/env sh
# Install these Agent Skills for every AI agent on this machine (macOS/Linux). Safe to re-run.
#   ~/.agents/skills -> Codex, Cursor, GitHub Copilot / VS Code
#   ~/.claude/skills -> Claude Code (Cursor reads it too)
set -eu
SRC="$(cd "$(dirname "$0")" && pwd)"
for dir in "$SRC"/*/; do
  [ -f "$dir/SKILL.md" ] || continue
  name="$(basename "$dir")"
  for t in "$HOME/.agents/skills" "$HOME/.claude/skills"; do
    mkdir -p "$t/$name"
    cp -R "$dir"* "$t/$name/"
    echo "installed $name -> $t/$name"
  done
done
echo "Restart your AI apps to pick up the skills."
