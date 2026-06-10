# Goal Operating System

This repository is a reusable, agent-friendly operating system for long-running personal goals.

It is designed to help a person and AI assistants preserve context, make decisions, plan in small units, review outcomes, and keep sensitive working notes private while sharing the public structure openly.

## What This Repo Contains

- Public templates for goals, plans, reviews, decisions, risks, and observations.
- Agent instructions for working with a continuity repository.
- A private vault workflow for sensitive context.
- Small tools for encrypting, restoring, and checking the repo before publication.

## Privacy Model

The public repo is a clean template. It should not contain real personal circumstances, active plans, identifying details, sensitive constraints, or private strategy.

Private working files are encrypted into `vault/private.bundle.enc`. On a trusted machine, restore them with:

```bash
uv run vault decrypt
```

Set `MY_DECODE_KEY` either in your shell or in a local `.env` file:

```bash
MY_DECODE_KEY="..."
```

`.env` is ignored by git and is never staged by the vault sync commands.

After editing private files, update the encrypted vault with:

```bash
uv run vault encrypt
```

To replace restored private files with safe public placeholders after encrypting:

```bash
uv run vault publicize
```

Before publishing or pushing, run:

```bash
uv run vault check
```

For normal trusted-machine sync, use:

```bash
uv run vault sync-pull
uv run vault sync-push
```

`sync-pull` refuses to pull if local changes could be lost, then restores the repo to decoded mode.
`sync-push` encrypts private files, temporarily writes public placeholders, commits and pushes the safe state, then restores decoded mode locally.
Use `uv run vault sync-push -m "Your message"` to customize the commit message.

Working-context roots are private by default: `context/`, `state/`, `observations/`, `research/`, `strategy/`, `dump/`, `lessons/`, and non-template files under `plans/`. New files in those areas are encrypted automatically. Public scaffolding stays in `tools/`, `plans/templates/`, and the top-level repo files.

## Repository Map

- `AGENTS.md`: operating instructions for AI agents.
- `context/`: durable background and operating constraints.
- `state/`: dashboard, backlog, risks, decisions, and current truth.
- `plans/`: current plans, dated plans, and reusable planning templates.
- `observations/`: raw notes that may later become lessons.
- `lessons/`: durable reusable lessons.
- `research/`: research notes and decision support.
- `strategy/`: strategic framing and tradeoffs.
- `tools/`: repo utilities.
- `vault/`: committed encrypted private bundle.
- `.vault/`: vault manifest and local vault metadata.

## Default Session Flow

1. Read `AGENTS.md`.
2. Read `state/dashboard.md`.
3. Read `plans/current.md`.
4. Review the active backlog and open questions.
5. Ask what changed since the last session.
6. Help choose one to three concrete next actions.

## Public Use

To adapt this repo for your own goals, keep the structure, rewrite the templates, set `MY_DECODE_KEY`, and use the vault commands to separate public scaffolding from private working context.
