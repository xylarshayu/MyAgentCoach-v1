---
name: live-research-plane
description: Route time-sensitive or practitioner-signal research across official primary sources, Reddit, Hacker News, and X/Twitter. Use for latest news, product limits, launches, community experience, fast-moving tooling, or any question where standard web results omit current field evidence.
---

# Live Research Plane

Use the narrowest source mix that can answer the question.

1. Establish current facts from official primary sources first.
2. Use Reddit for practitioner consensus and full comment-tree evidence.
3. Use Hacker News for technical reception and launch discussion. Query the keyless Algolia API
   described in `~/.claude/research-feeds.md`.
4. Use X for earliest reports, named-user experience, and fast-moving changes. Read the shared
   `twitterapi-io` skill completely before calling it; keep reads bounded because they are metered.
5. Separate the synthesis into **verified fact**, **anecdote**, and **inference**. Include dates
   and direct links. Never turn a fresh complaint into a policy claim without corroboration.

Prefer parallel subagents when the lanes are independent and the expected savings exceed
coordination cost. Default the evidence-gathering legs to an economical model such as Terra;
reserve the strongest/root model for conflict resolution and synthesis. Keep fan-out shallow.

Never expose API keys, cookies, private account data, or raw credential-bearing configuration.
