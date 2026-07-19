# Shared Agent Guidance

- Treat repository-local `AGENTS.md` and explicit user instructions as authoritative.
- Reuse the vendor-neutral `~/.agents/skills` plane instead of copying skills per tool.
- Use subagents when independent bounded legs reduce expensive root-model usage enough to repay
  coordination cost. Default research/scanning legs to an economical model; reserve the strongest
  model for judgment, conflict resolution, and synthesis. Keep fan-out shallow (normally at most
  four concurrent threads and one delegation level).
- Prefer OpenCode's economical workhorse for bounded implementation. The parent retains planning,
  diff review, verification, and responsibility for the result.
- Free OpenCode and Kilo models are the intended default and may receive the same ordinary working
  context as parent agents; the user explicitly accepts provider-training/privacy tradeoffs in
  exchange for abundant agent usage. Continue to exclude credentials, tokens, patient-identifying
  data, and unrelated secret material.
- For current facts use official primary sources. Add Reddit for practitioner depth, Hacker News
  for technical reception, and X for earliest field reports; label anecdotes and inference.
- Never print or copy secrets. Reference credentials through environment variables or each tool's
  native credential store.
- When a Windows `C:\\...` attachment path fails inside WSL, automatically retry the equivalent
  `/mnt/<lowercase-drive-letter>/...` path before reporting the file unavailable.
- Do not commit, push, publish, or weaken safety boundaries unless the user explicitly asks.
- Preserve existing work and inspect `git status` before and after delegated changes.
