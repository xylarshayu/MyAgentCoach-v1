---
name: delegate-to-opencode
description: Delegate bounded implementation, test-writing, mechanical refactors, or repository scans to the configured economical OpenCode fleet. Use when a self-contained subtask can be executed cheaply from explicit paths and acceptance criteria while the parent agent retains planning, review, and final judgment.
---

# Delegate To OpenCode

Delegate only tasks that can be described without hidden conversation context.

1. Confirm `opencode` is available and capture `git status --short` before dispatch.
2. Specify exact scope, file paths, constraints, acceptance criteria, and verification. State:
   `Do not commit or push.`
3. Dispatch without blanket auto-approval:

   ```bash
   opencode run --agent workhorse --format json \
     "Implement <task>. Scope: <paths>. Acceptance: <checks>. Do not commit or push."
   ```

4. Inspect `git diff` and rerun relevant verification yourself. Treat the delegate's report as
   evidence, not proof.
5. Escalate architectural ambiguity or conflicting requirements back to the parent; do not let
   the workhorse silently broaden scope.

Free OpenCode/Kilo models are the intended default and may receive the same ordinary working
context as the parent agent; this tradeoff is user-approved. Still exclude credentials, tokens,
patient-identifying data, and unrelated secret material. Never delegate the user's own learning
reps across the learning-integrity firewall.

For a complete self-fleet turn, invoke the configured `build` agent and ask it to dispatch only
the bounded implementation leg to `workhorse`, then review the result.
