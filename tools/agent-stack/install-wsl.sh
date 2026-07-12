#!/bin/sh
set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo=$(CDPATH= cd -- "$here/../.." && pwd)
stamp=$(date +%Y%m%dT%H%M%S)

backup_install() {
  src=$1
  dst=$2
  mode=${3:-644}
  mkdir -p "$(dirname "$dst")"
  if [ -e "$dst" ] && ! cmp -s "$src" "$dst"; then
    cp -a "$dst" "$dst.bak.$stamp"
  fi
  install -m "$mode" "$src" "$dst"
}

mkdir -p "$HOME/.local/bin" "$HOME/.agents/skills" "$HOME/.config/opencode" \
  "$HOME/.config/kilo" "$HOME/.codex" "$HOME/.codex-app"

ln -sfn "$HOME/.opencode/bin/opencode" "$HOME/.local/bin/opencode"
for tool in node npm npx kilo kilocode; do
  ln -sfn "$here/fnm-tool-wrapper" "$HOME/.local/bin/$tool"
done
ln -sfn "$here/reddit-mcp-buddy" "$HOME/.local/bin/reddit-mcp-buddy"

for skill in live-research-plane delegate-to-opencode; do
  ln -sfn "$repo/.agents/skills/$skill" "$HOME/.agents/skills/$skill"
done

backup_install "$here/opencode.jsonc" "$HOME/.config/opencode/opencode.jsonc"
backup_install "$here/kilo.jsonc" "$HOME/.config/kilo/kilo.jsonc"
backup_install "$here/global-guidance.md" "$HOME/.agents/global-guidance.md"
backup_install "$here/global-guidance.md" "$HOME/.codex/AGENTS.md"
backup_install "$here/global-guidance.md" "$HOME/.codex-app/AGENTS.md"

add_mcp() {
  codex_home=$1
  shift
  if ! CODEX_HOME="$codex_home" "$HOME/.local/bin/codex" mcp get "$1" >/dev/null 2>&1; then
    CODEX_HOME="$codex_home" "$HOME/.local/bin/codex" mcp add "$@"
  fi
}

for codex_home in "$HOME/.codex" "$HOME/.codex-app"; do
  add_mcp "$codex_home" openaiDeveloperDocs --url https://developers.openai.com/mcp
  add_mcp "$codex_home" reddit-mcp-buddy -- "$HOME/.local/bin/reddit-mcp-buddy"
done

echo "WSL agent stack installed. Run: $here/doctor.sh"
