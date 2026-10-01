# Codex Desktop on Windows with WSL

## Current findings — 2026-09-06

Verified on Windows Desktop **26.901.4073**, its bundled WSL CLI **0.153.1**,
and Ubuntu-24.04. The separately installed WSL CLI is still **0.144.2**.
The older workaround below is historical: **do not assume `.zshenv` controls
the current desktop app-server.**

The current app launches `/usr/bin/bash -lc`, injecting the Windows-mounted
`CODEX_HOME`, while explicitly placing `CODEX_SQLITE_HOME` at
`$HOME/.codex/sqlite`. The existing `.zshenv` override still changes tool shells
to the Linux Codex home. Consequently, the app-server, tool shells, and older
session files do not all use one home. Native SQLite storage is already provided
by the current app; moving all state back to `/mnt/c` is unnecessary.

### Confirmed failures

| Symptom | Evidence | Result / limitation |
| --- | --- | --- |
| Cannot create a project | Desktop project migration passes Windows UNC roots directly to Linux `project/import`; logs say `Invalid request: AbsolutePathBuf deserialized without a base path`. New project creation also sends UNC roots. | App conversion bug. Folder existence and Windows access both passed. A repair utility can register a specific project and repair legacy mappings while the app is closed. It does not patch the dialog. |
| Cannot archive some older tasks | SQLite contains a mixture of Linux-home and Windows-home rollout paths. `thread/archive` rejects a Linux-home rollout when the server uses the Windows home: `must be in sessions directory`. | Calling the same bundled app-server API with the rollout's owning home works. The reported task was archived and its database state verified. |
| Computer Use does not initialize | Windows `node_repl.exe` rejects `file:///home/...` with `sandboxCwd is not a local file URI`, before `@oai/sky` imports. | Direct tool remains broken. **Working fallback verified September 7:** an ephemeral native Windows Codex worker uses the normal plugin while the parent stays in WSL; see below. |
| Attached screenshots report file not found | The prompt supplied `C:\\Users\\...` to a Linux file reader. | Translate to `/mnt/c/Users/...` and use the normal image reader. Both supplied screenshots were read successfully. |

The project migration failure is recorded in the September 1–4 desktop logs,
including September 4 at 21:41:59 UTC. The code paths were checked in the installed
app bundle; no vendor binaries, permissions, or security checks were modified.

### Targeted repair utility

`tools/codex-wsl-repair.py` uses the **desktop-bundled** Linux app-server and its
current SQLite directory. It never modifies database rows directly or copies
conversation contents. All commands default to a dry run.

For the requested project, first inspect the plan from WSL:

```sh
python3 /home/xylar/personal/MyAgentCoach-v1/tools/codex-wsl-repair.py register-project \
  --name 'Smart Parcha' --path /home/xylar/projects/Smart-Parcha-V2
```

Then **fully quit Codex Desktop** and run this in an independent WSL terminal:

```sh
python3 /home/xylar/personal/MyAgentCoach-v1/tools/codex-wsl-repair.py register-project \
  --name 'Smart Parcha' --path /home/xylar/projects/Smart-Parcha-V2 --apply
```

The utility imports the existing and requested projects with Linux paths through
Codex's `project/import` API, verifies `project/read`, preserves cached project IDs
and ordering, and writes the legacy-to-core mapping used by this desktop build.
It backs up the desktop state under `~/.codex/repair-backups/` and refuses the
cache write if Codex is running or the file has changed. It preserves the current
selection, task assignments, and unrelated settings. Existing thread assignments
are left for the app's normal migration.

Live verification **passed on 2026-09-07** after the user ran the repair and
reopened Codex: the desktop project listing includes Smart Parcha at
`/home/xylar/projects/Smart-Parcha-V2` alongside all three pre-existing projects.
The app reports `projectsMigrated: true`, with all four legacy-to-core mappings
present. `threadAssignmentsMigrated` remains false; full task-assignment
migration is not claimed. The specified older task remains archived.
The real app-server API was also tested with an isolated fixture, including
preservation and idempotent reruns. Core-only project creation was not presented as
a sidebar fix: this app build does not automatically populate its desktop cache
from core-only projects.

Computer Use retest on 2026-09-07 (desktop 26.901.6511; plugin 26.901.51231)
still fails with the same `sandboxCwd is not a local file URI` error. The runtime
manifest still identifies the Windows Node REPL build
`0.0.9/20260829001140-68931e022688`; a plugin version change alone did not fix it.

### Working Computer Use fallback — verified 2026-09-07

The canonical shared skill is
`~/.agents/skills/windows-computer-use/SKILL.md`; its launcher is
`~/.agents/skills/windows-computer-use/scripts/run.py`. It launches the already
installed, relocated native Windows Codex CLI in an ephemeral session with a
Windows working directory. The parent task and desktop agent setting remain WSL.

The launcher reads the current desktop configuration on each invocation,
including the native CLI/runtime locations and current Computer Use pipe. It
overrides only the worker's Node REPL executable path to Windows form and
disables unrelated MCP servers for that invocation. The worker uses the normal
trusted `@oai/sky` service and reads the current plugin's instructions. No custom
Computer Use helper protocol, sandbox metadata rewriting, vendor patching, or
new CLI installation was required. Global configuration is not modified.

Verified outcomes:

- Native Node REPL initialized and `sky.list_apps()` returned 40 apps.
- An actual UI smoke test selected/launched Calculator, entered `7 × 8`, and
  verified the displayed answer `56`. Calculator was left open.
- The launcher defaults to economical `gpt-5.6-luna`, with a model override for
  more demanding tasks. The parent retains planning and final judgment.
- Skill validation, Python compilation, and Windows/WSL path conversion checks
  passed.

For future use, write a bounded authorized task to a text file and run:

```sh
python3 ~/.agents/skills/windows-computer-use/scripts/run.py \
  --task-file /absolute/path/authorized-task.txt
```

Keep the desktop open while the worker runs, and run only one UI worker at a
time. The parent should read the shared skill first. Each invocation observes
fresh windows and starts a new ephemeral session; handles and screenshot IDs
cannot be reused between workers. A final result is retained in the printed
Windows worker directory. Timeout/cancellation stops the worker's own process
tree; re-observe before retrying an interrupted UI operation.

The plugin's normal app restrictions and approval rules remain in force. Tasks
requiring approval/elicitation must stop at that point if the headless worker
cannot collect it; do not fabricate approval. The successful Calculator test
does not prove every approval-gated action works headlessly.

For another affected task, substitute its ID:

```sh
python3 /home/xylar/personal/MyAgentCoach-v1/tools/codex-wsl-repair.py archive TASK_ID
python3 /home/xylar/personal/MyAgentCoach-v1/tools/codex-wsl-repair.py archive TASK_ID --apply
```

Archiving uses the rollout's owning Codex home and verifies the resulting state.
It can run while the desktop is open. The utility does not archive additional
tasks automatically.

On another laptop, pass `--desktop-home /mnt/c/Users/WINDOWS_USER/.codex` before
the subcommand. Recheck the installed app version before reusing the project
cache repair on later versions: its cache fields are implementation details.

### Rollback and boundaries

For project-cache rollback, fully close Codex and restore the printed backup of
`.codex-global-state.json`. The imported core project records remain in the
database; this is a cache rollback, not a database rollback. The repair is
idempotent and can be rerun to restore the matching cache. Never copy a live
SQLite/WAL set, delete session history, or patch the runtime's path validation.

Changing only `CODEX_HOME` is not a complete repair: it swaps which historical
rollouts violate the archive directory check. The current Windows runtime also
does not gain Linux-path support from a shell-home change.

Official Windows setup documentation describes adding WSL folders through
`\\\\wsl$\\` and changing the agent environment with an app restart:
[Windows app / WSL documentation](https://learn.chatgpt.com/docs/windows/windows-app#windows-subsystem-for-linux-wsl).
The precise failure diagnoses above come from this machine's logs and installed
code, rather than from that general documentation.

## Historical June–July workaround

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
