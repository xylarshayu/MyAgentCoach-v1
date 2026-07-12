#!/bin/sh
set -u

fail=0
check() {
  label=$1
  shift
  if "$@" >/dev/null 2>&1; then
    printf 'ok   %s\n' "$label"
  else
    printf 'FAIL %s\n' "$label"
    fail=1
  fi
}

check "Codex CLI" "$HOME/.local/bin/codex" --version
check "OpenCode CLI" "$HOME/.local/bin/opencode" --version
check "Kilo CLI" "$HOME/.local/bin/kilo" --version
check "Node wrapper" "$HOME/.local/bin/node" --version
check "OpenCode config" test -f "$HOME/.config/opencode/opencode.jsonc"
check "Kilo config" test -f "$HOME/.config/kilo/kilo.jsonc"
check "shared live-research-plane skill" test -f "$HOME/.agents/skills/live-research-plane/SKILL.md"
check "shared delegate-to-opencode skill" test -f "$HOME/.agents/skills/delegate-to-opencode/SKILL.md"
check "WSL Codex OpenAI docs MCP" sh -c 'CODEX_HOME="$HOME/.codex" "$HOME/.local/bin/codex" mcp get openaiDeveloperDocs'
check "WSL Codex Reddit MCP" sh -c 'CODEX_HOME="$HOME/.codex" "$HOME/.local/bin/codex" mcp get reddit-mcp-buddy'

exit "$fail"
