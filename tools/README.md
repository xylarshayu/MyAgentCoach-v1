# Tools

This directory contains small utilities for managing the repository.

## Codex Desktop on Windows with WSL

See `tools/codex-desktop-wsl.md` for the workaround used when Codex Desktop on Windows launches WSL agents with `CODEX_HOME` under `/mnt/c`, making the app slow or laggy compared with direct WSL CLI.

## Vault

Use the vault command through `uv`:

```bash
uv run vault encrypt
uv run vault decrypt
uv run vault publicize
uv run vault check
uv run vault sync-pull
uv run vault sync-push
```

The vault uses `MY_DECODE_KEY` for encryption and decryption. Set it in the shell or in a local `.env` file:

```bash
MY_DECODE_KEY="..."
```

Public checks scan plaintext files for configured hazard terms and fail if private paths are staged with non-placeholder content.

Typical migration flow:

```bash
export MY_DECODE_KEY="..."
uv run vault encrypt
uv run vault publicize
uv run vault check
```

On a trusted machine, restore private files with:

```bash
uv run vault decrypt
```

For day-to-day syncing on a trusted machine:

```bash
uv run vault sync-pull
uv run vault sync-push -m "Sync goal system state"
```

`sync-pull` pulls latest Git changes and restores decoded files. `sync-push` encrypts private files, publicizes placeholders, commits and pushes safe paths, then restores decoded files locally.

`sync-push` encrypts working-context roots automatically: `context/`, `state/`, `observations/`, `research/`, `strategy/`, `dump/`, `lessons/`, and non-template files under `plans/`.

Public scaffolding belongs in explicit public areas such as `tools/`, `plans/templates/`, and top-level repo files. Unknown files outside the private roots and public allowlist fail closed so they can be deliberately classified instead of silently skipped or published.

Optional local-only hazard terms can be stored in `.vault/hazards.local.json` using the same `hazard_terms` array shape as the manifest. That file is ignored by git.

Keep tools small, boring, and easy to run from a fresh clone.
