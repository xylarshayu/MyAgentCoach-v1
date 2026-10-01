# Handoff: Codex Desktop cannot create a project in WSL2

## Request to the receiving Codex agent

My Windows Codex Desktop is using a WSL2 agent and fails to create a project.
Please diagnose whether this is the same Windows/WSL project-path conversion bug
and, if so, use the attached repair script to register my requested project.
Determine this laptop's actual paths and installed versions first. Preserve my
existing projects, task assignments, history, and settings. Do the work rather
than just explaining it. Coordinate one full app-close/reopen cycle for the
sidebar-cache write; prepare everything before asking me to close the app.

Ask me for the desired project name and Linux folder if I have not supplied them.
Do not assume the Windows username, WSL username, or distribution from another
machine. This handoff covers project registration; do not change the agent
runtime, migrate session history, install packages, or modify security settings.

## What happened on the source laptop

Observed September 6–13, 2026. Codex Desktop on Windows ran its app-server inside
Ubuntu-24.04. The project folder existed and was readable from Windows through
both `\\wsl$\DISTRO\...` and `\\wsl.localhost\DISTRO\...`.

The UI displayed `Failed to create project`. The actionable desktop log was:

    [host-app-server-projects] Local app-server project migration failed
    Invalid request: AbsolutePathBuf deserialized without a base path

Inspection of the installed app showed:

1. Desktop stored project folders as Windows UNC paths.
2. It sent those paths unchanged to the Linux app-server's `project/import`
   and project-create/update paths.
3. The Linux absolute-path parser rejected the UNC strings.
4. Existing-project migration could therefore block new project creation too.

This was a product path-conversion bug, not a missing folder or bad spelling.
The source machine also had an older `.zshenv` CODEX_HOME override. Removing or
expanding that override was not needed for this project repair.

## What actually fixed project registration

Use the same desktop-bundled Linux Codex binary and the same SQLite directory
that the running desktop app-server uses. Through Codex's app-server API, import
the desired project with a POSIX Linux root such as `/home/USER/projects/REPO`.
Then, while the desktop is FULLY CLOSED, back up and update its desktop project
cache plus the legacy-project-ID to core-project-ID mapping.

Core API creation alone was insufficient: the inspected desktop did not populate
its sidebar cache from core-only projects. We preserved the existing cached IDs,
ordering, selected project, task assignments, and unrelated fields. We did not
edit SQLite rows directly, copy conversation files, or patch app binaries.

The included script implements that targeted workaround:

- Dry-run by default.
- Uses `project/import` and `project/read` with experimental API negotiation.
- Converts WSL UNC roots to Linux paths and rejects another distribution's roots.
- Uses stable idempotency keys to avoid duplicate imports on rerun.
- Preserves existing desktop project IDs and ordering.
- Backs up `.codex-global-state.json` under the current WSL user's
  `~/.codex/repair-backups/` before mutation.
- Refuses a cache write while Codex/ChatGPT Desktop is running or when the cache
  changed after the snapshot.
- Optionally waits up to ten minutes for the desktop to close before taking that
  snapshot and applying the repair.

This is an app-version-dependent workaround, not an official patch. It registers
the requested project and repairs mappings; it does not fix the New Project
button for every future project.

## Adapt to this laptop before running

1. Determine the active WSL distribution (`WSL_DISTRO_NAME`), Linux user/home,
   Windows user/home, requested project folder, and desired display name.
2. Inspect only relevant process environment fields for the desktop app-server:
   `CODEX_HOME`, `CODEX_SQLITE_HOME`, and its executable path. Do not print the
   whole environment or read authentication files.
3. Check the actual desktop logs for the error above. Typical location:
   `%LOCALAPPDATA%/Packages/OpenAI.Codex_*/LocalCache/Local/Codex/Logs/`.
4. On the source laptop the desktop backend used Windows-mounted CODEX_HOME and
   native WSL `CODEX_SQLITE_HOME=$HOME/.codex/sqlite`. The script assumes that
   SQLite directory. If this machine differs, adapt the script deliberately
   before executing; do not point it at a guessed database.
5. Select the actual running desktop-bundled Linux binary with `--binary`.
   Do not substitute an older standalone WSL CLI. Check that the installed
   protocol still supports the project APIs and current cache layout. The first
   source repair used bundled CLI 0.153.1 / desktop 26.901.4073 and was verified
   after updating to 0.153.4 / desktop 26.901.6511. A second project registration
   also completed successfully on September 13 with that day's bundled binary.
6. Existing cached project folders must still exist. The script deliberately
   stops rather than silently removing missing or differently named projects.

## Commands (replace placeholders; run from WSL)

Dry run:

```sh
python3 /path/to/codex-wsl-repair.py \
  --desktop-home /mnt/c/Users/WINDOWS_USER/.codex \
  --binary /actual/path/to/desktop/bundled/linux/codex \
  register-project --name 'DESIRED PROJECT NAME' \
  --path /home/LINUX_USER/projects/REPO
```

Apply from an independent WSL terminal, then fully quit Codex Desktop:

```sh
python3 /path/to/codex-wsl-repair.py \
  --desktop-home /mnt/c/Users/WINDOWS_USER/.codex \
  --binary /actual/path/to/desktop/bundled/linux/codex \
  register-project --name 'DESIRED PROJECT NAME' \
  --path /home/LINUX_USER/projects/REPO \
  --apply --wait-for-desktop-exit
```

Alternatively, quit the desktop first and omit `--wait-for-desktop-exit`.
Do not launch the waiting command in a terminal that closes with the app. The
source agent opened an independent Windows-hosted WSL terminal for the user.
A restart is not authorization to forcibly terminate other active work.

## Verify before declaring success

- The repair exits zero and prints its backup path.
- Reopen the desktop; `list_projects` and the sidebar show the requested project
  with the correct Linux root.
- Existing projects, selection, and task assignments are preserved.
- The desktop migration mapping includes the new project. Do not claim all task
  assignments migrated just because `projectsMigrated` is true.

Source verification: the first project appeared in `list_projects` alongside all
three original projects. An isolated real app-server test also verified imports,
readback, cache preservation, and idempotent reruns. The September 13 follow-up
repair reported success and exit code zero; the desktop project listing then
confirmed the second project with its correct root and all existing projects.

## Rollback / privacy

With the desktop closed, restoring the printed `.codex-global-state.json` backup
rolls back its cache. Imported core project records remain: that is not a full
database rollback. Idempotent reruns restore matching mappings. Do not delete
core records indiscriminately or copy live SQLite/WAL files.

This export contains only instructions and source code. Never attach auth.json,
actual global-state files, database backups, private conversations, or tokens
when forwarding it. The script also has an archive subcommand, but it is outside
this project's requested repair and should not be run unless separately needed.
