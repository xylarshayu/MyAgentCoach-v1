# Personal Agent Stack Handover

Canonical personal stack: Codex for high-judgment orchestration, OpenCode for economical bounded
execution, Kilo as an alternate harness, and `~/.agents/skills` as the shared capability plane.
Cursor is intentionally excluded from the personal laptop; it remains a separate work-plane tool.

**After cloning on a work machine:** start with
[`WORK-LAPTOP-INTEROP.md`](WORK-LAPTOP-INTEROP.md). It is the operational recipe for the
Cursor CLI ⇄ OpenCode lanes, their safety boundaries, and a short proof sequence. It deliberately
distinguishes the personal stack that is installed here from the work-plane setup that still needs
to be installed and tested on that machine.

## Install

From WSL:

```bash
chmod +x tools/agent-stack/install-wsl.sh tools/agent-stack/doctor.sh \
  tools/agent-stack/fnm-tool-wrapper tools/agent-stack/reddit-mcp-buddy
tools/agent-stack/install-wsl.sh
```

From Windows PowerShell:

```powershell
& "\\wsl.localhost\Ubuntu-22.04\home\xylar\personal\MyAgentCoach-v1\tools\agent-stack\install-windows.ps1"
```

Restart Codex Desktop, then run `tools/agent-stack/doctor.sh` in WSL. Inspect the config before
accepting any model-backed smoke test. The installers back up changed global files with a dated
`.bak.*` suffix and do not copy credentials.

## Model-routing default

- Codex Terra subagents: read-only research and repository scans.
- Codex Sol/root: judgment, conflict resolution, synthesis, and hard knots.
- OpenCode MiMo V2.5 Free: planner/reviewer.
- OpenCode DeepSeek V4 Flash Free: bounded implementation workhorse.
- Kilo North Mini Code Free: alternate free harness, sandboxed with network denied by default.

## Validated personal handoff (2026-07-12)

The `build → workhorse` OpenCode path is now proven with a disposable no-op edit: the planner
delegated via its native `task` tool, the workhorse changed only the sentinel file, and returned
the result. The planner has its `skill` tool disabled so it cannot recursively load the
`delegate-to-opencode` skill intended for an outer orchestrator. Its edit permission remains
denied and its shell permission remains ask-by-default with a narrow read-only Git allowlist.

This proves bounded execution, not broad autonomous review. Keep Codex responsible for judgment,
architecture, and diff review; give OpenCode explicit paths, acceptance checks, and no-commit
constraints.

Free providers may use prompts for model improvement. Ayush explicitly accepts that tradeoff and
wants these agents to access ordinary shared working context. Credentials, tokens,
patient-identifying data, and unrelated secret material remain excluded.

At 00:04 IST on 2026-07-12, one Sol session with three parallel research agents exhausted the
available session allowance. Treat that as measured evidence for economical routing, not as a
ban on subagents: fan out when lanes are independent, use cheaper workers, and keep depth at one.
