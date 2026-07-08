# Roadmap: Make remote-mcp the default Python remote MCP scaffolder

Status: draft, 2026-06-03
Owner: @pushpendra-tripathi

## North star

> "I'm a Python dev with an OAuth API. In 10 minutes my API is a remote MCP
> server connected to Claude/Cursor/ChatGPT, deployed to production, with
> tests and telemetry already wired."

## Target user

**Primary**: Python SaaS engineer (Django/Flask/FastAPI background) at a
5–500 person company with an existing OAuth2 backend, asked by their PM to
"ship MCP integration this sprint."

**Secondary**: indie hacker building an AI-first product who wants an MCP
server for their own SaaS.

**Not target**: hobbyist building stdio MCP for personal tools (use raw
FastMCP). LangChain refugees (different problem).

## Pain → feature map

| User pain | Today | Plan to fix |
|-----------|-------|-------------|
| "MCP spec moving — SSE/streamable-http confusion" | SSE only | Phase 1: dual transport |
| "How do I deploy this?" | DEPLOYMENT.md text | Phase 1: deploy buttons + scripts |
| "Backend isn't Django-OAuth-Toolkit, defaults wrong" | Configurable now | Phase 2: presets per backend |
| "How do I integrate Stripe/GitHub/Notion API?" | Empty `tools/` | Phase 2: backend recipes |
| "How do I test without Claude?" | Manual curl | Phase 2: Inspector profile |
| "Is my server compat with Claude.ai vs ChatGPT vs Cursor?" | Unclear | Phase 2: compat matrix + smoke |
| "Tokens expiring randomly in prod" | Auth probe optional | Phase 3: refresh-flow recipe |
| "1000s of users — does this scale?" | No guidance | Phase 3: scale guide + load test |
| "MCP changed, my scaffold rotting" | No update path | Phase 3: `doctor` + diff helper |
| "Want to demo before scaffolding" | None | Phase 3: hosted demo |

## v1.0.0 shipped

Pulled Phase 2 item 9 forward, broadened it into a source axis (`add openapi`
+ `add database`), and pulled Phase 3 item 16 (`doctor`, report-only) forward
alongside it to give the release a retention loop. CLI surface declared
stable at 1.0.0 — breaking CLI changes require a major bump from here on.
Design + rationale: `docs/superpowers/specs/2026-07-02-source-generators-design.md`.
Release-checklist items from that design (PyPI/star baseline, demo recording,
launch post, FastMCP outreach) are still open and owned by the maintainer,
not tracked as code work.

## Roadmap

### Phase 1 — Launch + visibility (2 weeks, ship v0.3.0)

Goal: get on the map. Cross 500 PyPI downloads/week, 100 GitHub stars.

1. **streamable-http transport** alongside SSE. Add `--transport sse|http|both`
   flag. Default `both`. (1d) — **DONE v0.3.0** (shipped as `/mcp` default + `--legacy-sse` opt-in, not `--transport both`).
2. **One-click deploy buttons** in generated README: Render, Railway, Fly.io,
   Vercel. Pre-tested config files in template. (1d)
3. **Polish demo path**: animated terminal recording (asciinema),
   `remote-mcp new → cd → uvicorn → connect to Claude.ai` in ≤ 90s. Embed in
   repo README. (0.5d)
4. **MCP Inspector preset**: generated `mcp.json` so
   `npx @modelcontextprotocol/inspector` Just Works. (0.5d)
5. **Blog post + tweet thread**: "Production remote MCP in 10 minutes."
   Submit to HN (Show HN), Reddit (r/Python, r/LocalLLaMA, r/ClaudeAI),
   Awesome MCP lists, FastMCP Discord. Tag Anthropic devrel + FastMCP author
   on Twitter. (1d)
6. **PyPI page polish**: long_description, badges, screenshots. (0.5d)
7. **OAuth presets**:
   `remote-mcp new --oauth=django-oauth-toolkit|auth0|clerk|cognito|custom`
   sets defaults. (1d)
8. **Auth0 + Clerk + Cognito tutorials** in `docs/integrations/`. (2d)
9. **Registry publishing** — generated `server.json` + `.github/workflows/publish-mcp.yml`. **DONE v0.3.0**.

### Phase 2 — Problem solver (4 weeks, ship v0.4.0)

Goal: be the obvious choice. Cross 2k downloads/week, 300 stars.

9.  **`remote-mcp from-openapi`**: generate a tools file from an OpenAPI spec — selected endpoints become MCP tools with auth, retry, and tests. Supersedes hand-maintained per-vendor recipes. (1w) — **DONE v1.0.0** (shipped as `remote-mcp add openapi`, broadened to a source axis alongside `add database`; see design doc below).
10. **Compatibility matrix doc**: hand-tested support for Claude.ai web,
    Claude Desktop, Claude Code, ChatGPT, Cursor, Windsurf, Continue.
    Document quirks per client. (3d)
11. **e2e auth flow test**: integration test in scaffold that boots a mock
    OAuth provider + verifies full handshake. (3d)
12. **`remote-mcp dev` command**: runs uvicorn + MCP Inspector + log tailing
    in one terminal. Replaces 3 separate commands. (2d)
13. **Refresh token recipe**: optional middleware that refreshes Bearer when
    401 from backend. Off by default. (2d)
14. **Async retry tuning guide**: docs on tenacity knobs, when to disable,
    idempotency rules. (1d)
15. **Telemetry dashboard**: small standalone `remote-mcp logs` command
    tailing the JSONL with rich table output. (2d)

### Phase 3 — Stickiness (8 weeks, ship v0.5.x)

Goal: keep users. Cross 5k downloads/week, 600 stars, 50+ projects in
showcase.

16. **`remote-mcp doctor`**: scans scaffolded project, reports drift from
    latest template + suggests upgrades. (1w) — **DONE v1.0.0**, report-only
    (manifest drift, generator-version drift, local modifications, and
    `--refresh` source drift). Applying fixes automatically stays
    `upgrade --dry-run` (item 17, still open).
17. **`remote-mcp upgrade --dry-run`**: diff current files against latest
    template, apply user-approved patches. Hard problem but high stickiness.
    (2w)
18. **Production hardening guide**: rate-limit middleware recipe, Sentry
    integration, Prometheus metrics endpoint, Datadog APM hook. (1w)
19. **Load test recipe**: k6/locust script in `tests/load/`. Document scale
    results (RPS / concurrent users / latency). (3d)
20. **Showcase**: `showcase.md` listing real deployed remote-mcp servers.
    Solicit submissions. (ongoing)
21. **Newsletter / changelog substack**: monthly digest of MCP ecosystem +
    remote-mcp changes. Builds owned audience. (ongoing)

### Phase 4 — Optional scale bets (3 months, evaluate after Phase 3)

22. **TypeScript variant** (`remote-mcp new --lang=ts`): emits Hono/Cloudflare
    Workers code. Doubles market but doubles maintenance. Decide based on
    Phase 3 signals.
23. **Hosted demo**: `try.remote-mcp.dev` — paste OAuth backend URL, get a
    live MCP server URL for 1 hour. Lead-gen funnel.
24. **`remote-mcp.com`**: docs site, blog, hosted scaffolder UI. SEO play.
25. **Anthropic / FastMCP partnership**: pitch as "official Python remote
    scaffolder." If they ship their own, donate code + retire.

## Success metrics

Track weekly. Public dashboard if possible.

| Metric | Phase 1 | Phase 2 | Phase 3 |
|--------|---------|---------|---------|
| PyPI downloads / week | 500 | 2k | 5k |
| GitHub stars | 100 | 300 | 600 |
| Showcase projects | 5 | 20 | 50 |
| Open issues | <10 | <20 | <30 |
| Time-to-first-tool (user opens → tool returns first response) | 10 min | 5 min | 3 min |
| Generated-project test pass rate | 100% | 100% | 100% |

## Risks + mitigations

| Risk | Mitigation |
|------|------------|
| Anthropic ships official remote scaffolder | Stay ahead on backends/recipes; position as "deeper than starter" |
| FastMCP 4.x breaking change | CI smoke against FastMCP main weekly; pin in generated lock |
| MCP transport churn (SSE → streamable-http → ?) | Generate transport-agnostic core; transport is one file |
| Maintainer burnout (one person) | Recruit 1–2 collaborators by Phase 2; doc CONTRIBUTING well |
| Niche too small (Python remote MCP <100 users worldwide) | Validate in Phase 1 before Phase 2 investment |
| Security incident in generated code | SECURITY.md exists; add `safety` + `pip-audit` to CI |

## Anti-goals (do NOT do)

- **Do not** add a runtime dependency from generated project to `remote-mcp`
  package. The "you own the code" promise is the differentiator. Break it =
  become a framework, lose moat.
- **Do not** maintain 5 backend recipes if only 1 has adoption. Drop fast.
- **Do not** chase ChatGPT-only or Cursor-only features that fragment compat.
  Aim for the common subset.
- **Do not** bundle UI framework choice (React/HTMX) in landing page. Static
  HTML stays.
- **Do not** add LLM-routing / agent-orchestration features. That's LangGraph
  territory.
- **Do not** rewrite in Rust for "speed." CLI runs once.

## Decision gates

- **End of Phase 1 (2 weeks)**: if <100 stars and <300 downloads/week, abort
  Phase 2. Pivot to TS-only or donate to FastMCP.
- **End of Phase 2 (6 weeks)**: if recipes get <3 install/week each, drop
  them; keep core.
- **End of Phase 3 (14 weeks)**: if no enterprise interest + no contributors +
  flat growth, archive and write retrospective post.

## Immediate next actions (this week)

1. Open GitHub issues for each Phase 1 item (8 issues).
2. Reach out to FastMCP maintainer — coordinate, don't compete.
3. Draft blog post outline.
4. Record current state demo GIF.

## Competitor landscape (snapshot 2026-06)

| Tool | Lang | Remote OAuth | Audit-friendly | Python |
|------|------|------|------|------|
| FastMCP examples | Py | partial | yes | yes |
| Anthropic MCP SDK templates | TS/Py | stdio only | yes | partial |
| Cloudflare Workers MCP starter | TS | yes | no (Workers-locked) | no |
| Vercel MCP starter | TS | partial | partial | no |
| **remote-mcp** | Py | full | yes | yes |

Niche where we win: **Python SaaS vendor wants OAuth-protected MCP server in
10 min, deployed to Render/Fly/own K8s, owning every line.**
