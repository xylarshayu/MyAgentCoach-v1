# Codex Desktop on Windows with WSL

This note captures a workaround for Codex Desktop feeling very slow or laggy when the agent environment is WSL.

## Symptom

- Codex CLI inside WSL is reasonably fast.
- Codex Desktop on Windows is much slower in the same WSL repo.
- Desktop agent diagnostics show `CODEX_HOME` under `/mnt/c/Users/<user>/.codex`.
- The Desktop-launched tool shell may have a different `PATH` from the normal interactive WSL terminal.

Related upstream issue: <https://github.com/openai/codex/issues/13762>

## Quick Diagnosis

In a Codex Desktop thread, run:

```text
Diagnostics only. Run:
printf 'ORIGIN=%s\nCODEX_HOME=%s\nSHELL=%s\nPATH_HEAD=%s\nUV_CACHE_DIR=%s\n' "$CODEX_INTERNAL_ORIGINATOR_OVERRIDE" "$CODEX_HOME" "$SHELL" "$(printf '%s' "$PATH" | cut -d: -f1-6)" "$UV_CACHE_DIR"
codex --version
codex doctor --summary
```

If output includes:

```text
ORIGIN=Codex Desktop
CODEX_HOME=/mnt/c/Users/<user>/.codex
```

then the Desktop WSL agent is using Windows-mounted state from inside WSL. That can make SQLite, worktree, cache, and Git operations slower or more fragile than native WSL storage.

## Workaround

Add this guarded block to `~/.zshenv` inside WSL:

```sh
# Codex Desktop on Windows launches WSL agents with CODEX_HOME on /mnt/c.
# Keep Desktop-launched Codex on the same native-WSL home as the standalone
# WSL CLI. This avoids slow Windows-mounted SQLite/worktree/cache access and
# makes the Desktop WSL app-server and CLI use the same backend state.
if [ "${CODEX_INTERNAL_ORIGINATOR_OVERRIDE:-}" = "Codex Desktop" ]; then
  export CODEX_HOME="$HOME/.codex"
  export PATH="$HOME/.local/bin:$PATH"
  export UV_CACHE_DIR="/tmp/uv-cache"
fi
```

Create the directories:

```sh
mkdir -p "$HOME/.codex" /tmp/uv-cache
```

Fully quit and reopen Codex Desktop. Then verify in a new Desktop thread:

```text
Diagnostics only. Run:
printf 'ORIGIN=%s\nCODEX_HOME=%s\nPATH_HEAD=%s\nUV_CACHE_DIR=%s\n' "$CODEX_INTERNAL_ORIGINATOR_OVERRIDE" "$CODEX_HOME" "$(printf '%s' "$PATH" | cut -d: -f1-4)" "$UV_CACHE_DIR"
codex --version
```

Expected:

```text
ORIGIN=Codex Desktop
CODEX_HOME=/home/<user>/.codex
UV_CACHE_DIR=/tmp/uv-cache
```

## Why `.zshenv`

Use `~/.zshenv`, not `~/.zshrc`, because Codex Desktop tool execution may use non-interactive zsh shells. `~/.zshrc` is mainly for interactive shell setup and may not affect agent commands.

The guard keeps the change scoped to Codex Desktop. Ordinary WSL shells and standalone `codex`
CLI runs keep their normal `CODEX_HOME`, which is the same `~/.codex` directory in this setup.

This shares the app-server's configuration, SQLite state, and rollout files. It does **not**
guarantee that the Windows Desktop sidebar will index or resume every CLI-created conversation.
The Windows UI keeps a separate host-keyed catalog under the Windows Codex home; current builds
can leave that catalog empty even when the WSL app-server's `thread/list` returns the CLI threads.
Treat sidebar visibility and shared backend state as separate checks.

If Desktop and CLI must remain deliberately isolated, use `$HOME/.codex-app` instead. That keeps
Desktop fast, but it also creates a separate configuration and local session-history plane; CLI
chats will not appear in Desktop unless the two Codex homes are synchronized separately.

## Notes

- Do not symlink the entire Windows `.codex` directory into WSL. That keeps the `/mnt/c` performance problem.
- OpenAI's documented default is that the Windows app uses `%USERPROFILE%\.codex`, while a WSL
  CLI uses `~/.codex`; they do not automatically share config, cached auth, or local session
  history. This guarded override is an adapted native-WSL alternative to putting WSL CLI state
  under `/mnt/c`.
- Do not live-copy or symlink `state_*.sqlite`, WAL/SHM files, or the Windows `codex-dev.db`
  between homes. The Windows sidebar catalog is not the source of truth for WSL rollouts, and
  current Windows builds have known sidebar/deep-link synchronization bugs. Preserve the WSL
  rollout files and use `codex resume --all` when Desktop cannot surface an existing thread.
- Do not copy or print `auth.json` contents.
- If auth breaks after changing `CODEX_HOME`, prefer logging in again from the affected context or copying only minimal non-secret config after inspecting what is missing.
- `UV_CACHE_DIR=/tmp/uv-cache` is not the main Codex speed fix. It avoids a separate `uv` cache/read-only mismatch seen in Desktop tool execution and is safe because it is inside the Desktop-only guard.
- `codex doctor --summary` inside Desktop may still report network failures if the tool shell is sandboxed. Compare with direct WSL `codex doctor` before treating that as a real WSL network problem.

## Rollback

Remove the guarded block from `~/.zshenv`, fully quit Codex Desktop, and reopen it.
