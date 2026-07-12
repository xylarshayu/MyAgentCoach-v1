# Work-Laptop Agent Interop — Start Here

This is the operational handover for a machine where Cursor CLI is available and OpenCode is the
economical overflow executor. It does **not** install anything by itself: first inspect the
employer's current policy and the local tool versions, then have the local Codex agent apply only
the pieces that fit that machine.

## The durable architecture

One shared capability plane is the point of interop:

```text
<repo>/.agents/skills/  ← shared instructions for Codex, Cursor, and OpenCode
          │
          ├─ Cursor agent / `agent` CLI: strong, company-sanctioned lane
          └─ OpenCode: build planner → cheap workhorse for bounded execution
```

Do not make every tool call every other tool. That creates duplicated context, permission holes,
and a second orchestration problem. Use these two deliberate lanes:

1. **Cursor → OpenCode (normal delegation).** Cursor has the task context and invokes a bounded
   `opencode run --agent workhorse` job through a shared skill. Give it exact paths, acceptance
   checks, and `Do not commit or push.` Cursor reviews the returned diff.
2. **OpenCode → Cursor CLI (exception lane).** Use the local `agent` CLI only when Cursor's
   stronger long-context judgment is materially useful. Prefer a review-only call first. A local
   OpenCode plugin/tool may wrap `agent -p --output-format json <task>` once the direct command
   has been proven. Do not default to `--force`.

Codex can sit above either lane for architectural judgment and final review. It is intentionally
removable: OpenCode's native `build → workhorse` fleet must remain able to execute bounded work
without Codex.

## Non-negotiable boundaries

- Do not proxy or tunnel a company Cursor subscription into personal tools or third-party model
  gateways.
- Never send credentials, tokens, patient-identifying data, or unrelated secrets to any agent.
- Do not add the large `opencode-mcp` bridge as the default. Its broad tool surface adds context
  and approval complexity; the shell-skill handoff is the baseline.
- Every delegated implementation says: exact scope, acceptance checks, verification command,
  **no commit or push**. The outer agent reviews the diff itself.

## Setup order on the work laptop

1. **Orient without changing state.** Check the current `agent` (Cursor CLI) and `opencode`
   versions, the repository's `AGENTS.md`, and company policy. Do not copy this personal
   machine's absolute paths or credentials.
2. **Install the common plane.** Keep reusable skills in `<repo>/.agents/skills/`; Cursor and
   OpenCode discover that location natively. Add a `delegate-to-opencode` skill that names the
   allowed OpenCode agent and its no-commit contract.
3. **Configure OpenCode as a real fleet.** Pin a planning model to `build` and an economical model
   to `workhorse`; keep `build` edit-denied, allow it to task only `workhorse`, and keep the
   workhorse able to edit only after the outer tool authorizes the run. The personal reference
   configuration is [`opencode.jsonc`](opencode.jsonc), but replace any machine-specific paths.
4. **Give Cursor the narrow permission it needs.** Permit only the OpenCode command and read-only
   Git inspection in the Cursor project settings. Do not blanket-authorize shell commands.
5. **Prove each lane before real work.** Use the smoke sequence below and record failures as
   stack evidence rather than papering over them with `--auto`.

## Smoke sequence

Run these in order on a disposable or non-sensitive fixture:

1. OpenCode native fleet: `build` delegates one one-line edit to `workhorse`; verify the exact
   diff and that no commit exists.
2. Cursor → OpenCode: ask Cursor to issue one bounded workhorse request; inspect the returned
   diff in Cursor and revert only the disposable fixture if desired.
3. OpenCode → Cursor: have OpenCode ask `agent -p --output-format json` for a **review-only**
   response on a tiny diff. No `--force`, no edit permission, no subscription proxy.
4. Real slice: one low-risk test or mechanical refactor. Codex/Cursor reviews it; compare the
   friction with doing the same task directly in Cursor.

If a step fails, stop at that lane. Do not solve a permission mismatch by granting blanket shell
access or using `--auto`.

## Current evidence and limits

- **Personal lane validated 2026-07-12:** the OpenCode `build → workhorse` handoff completed a
  disposable exact edit after the planner's skill tool was disabled. The planner remains
  edit-denied and shell-restricted.
- **Broad free-worker review is not yet dependable:** it can waste context reading whole files and
  fail to return a concise verdict. Keep reviews with Codex/Cursor; reserve OpenCode for bounded
  implementation and focused tests.
- **Work-laptop Cursor lanes are documented, not yet installed or smoke-tested.** That is the
  next machine-local task, not an assumption.

## Sources already in this repo

- Detailed architecture and economics:
  [`research/2026-07-11-agent-fleet-playbook.md`](../../research/2026-07-11-agent-fleet-playbook.md)
- Exact Cursor ⇄ OpenCode options and caveats:
  [`research/2026-07-11-cursor-opencode-interop.md`](../../research/2026-07-11-cursor-opencode-interop.md)
- The ruled personal-trial and team-rollout plan:
  [`plans/2026-07-11-agent-fleet-plan.md`](../../plans/2026-07-11-agent-fleet-plan.md)
