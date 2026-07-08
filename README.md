# remote-mcp

One command to a production-ready remote MCP server.

[![PyPI](https://img.shields.io/pypi/v/remote-mcp)](https://pypi.org/project/remote-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/remote-mcp)](https://pypi.org/project/remote-mcp/)
[![CI](https://github.com/pushpendra-tripathi/remote-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/pushpendra-tripathi/remote-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/pushpendra-tripathi/remote-mcp/blob/main/LICENSE)

---

Building a remote MCP (Model Context Protocol) server means solving the same hard problems every time: OAuth pass-through, RFC 8414/9728 discovery endpoints, middleware stack, telemetry, retry logic, Docker packaging, and a test suite that passes on day one.

`remote-mcp` scaffolds all of it. Generated projects have **zero runtime dependency** on this package — every file is yours to read, audit, and modify.

## Install

```bash
pipx install remote-mcp   # recommended
# or
pip install remote-mcp
```

## Usage

Interactive:

```bash
remote-mcp new my-project
```

Non-interactive (CI / scripts):

```bash
remote-mcp new my-project --yes --service-name "My Project" --into ./apps/my-project
```

```
  FastMCP Remote Server Generator

  Scaffolding my-project into my-project...
  ✓ Scaffold complete

  Done! Next steps:
    cd my-project
    python -m venv venv && source venv/bin/activate
    pip install -e ".[dev]"
    cp env.example .env
    uvicorn asgi:application --reload --port 8001 --lifespan on
```

Server is live at `http://localhost:8001`. MCP endpoint: `http://localhost:8001/mcp`.

Also works as a module:

```bash
python -m remote_mcp new my-project
```

## Commands

| Command | What it does |
|---------|--------------|
| `remote-mcp new <name>` | Scaffold a new project |
| `remote-mcp add tool <name>` | Add a tool stub to an existing scaffolded project |
| `remote-mcp add openapi <SPEC>` | Generate typed MCP tools from an OpenAPI 3.x spec — requires `pip install 'remote-mcp[openapi]'` |
| `remote-mcp add database <DSN>` | Generate read-only MCP tools from a live database schema — requires `pip install 'remote-mcp[db]'` |
| `remote-mcp doctor` | Report drift between `sources.lock.json` and reality |
| `remote-mcp --version` | Print version |

`new` flags:

| Flag | Purpose |
|------|---------|
| `--yes / -y` | Skip prompts; use defaults / provided flags |
| `--service-name / -s "Foo Bar"` | Human-readable service name |
| `--into PATH` | Target directory (default `./<name>`) |
| `--auth-mode none\|passthrough\|jwt` | Default auth mode for the generated project (default: passthrough) |
| `--github-owner OWNER` | GitHub user/org for the MCP registry namespace in server.json |
| `--legacy-sse` | Also serve the deprecated SSE transport at /sse |

`add tool` flags:

| Flag | Purpose |
|------|---------|
| `--project-dir / -p PATH` | Target project (default `.`) |

See [Sources](#sources) below for `add openapi`, `add database`, and `doctor` flags.

## What you get

```
my-project/
├── src/
│   ├── server.py              # FastMCP("My Project") instance + tool mounts
│   ├── app.py                 # Starlette factory — routes, middleware, ASGI wiring
│   ├── config/settings.py     # Pydantic BaseSettings (lazy get_settings())
│   ├── core/
│   │   ├── auth.py            # extract_bearer_token() — OAuth pass-through
│   │   ├── errors.py          # MyProjectError hierarchy
│   │   ├── http_client.py     # api_get/post/patch/put/delete/upload + tenacity retry
│   │   ├── telemetry.py       # JSONL event log, HMAC-salted user-id hashing
│   │   ├── handlers.py        # @tool_handler decorator, get_client_and_token()
│   │   └── app_state.py       # lifespan: shared httpx.AsyncClient pool
│   ├── middleware/
│   │   ├── auth.py            # RequireAuthMiddleware — Bearer enforcement + probe
│   │   └── telemetry.py       # TelemetryMiddleware — auth failures, connections
│   ├── views/
│   │   ├── health.py          # GET /health
│   │   ├── oauth.py           # RFC 8414 + RFC 9728 discovery endpoints
│   │   └── root.py            # landing page at /
│   └── tools/example.py       # echo tool — mounted and live at first boot
├── tests/
│   ├── test_auth.py           # extract_bearer_token edge cases
│   ├── test_middleware.py     # auth bypass, 401 on missing token
│   └── test_telemetry.py      # hash_token stability, record_event never raises
├── templates/index.html       # landing page served at /
├── Dockerfile                 # multi-stage, non-root, healthcheck
├── docker-compose.yml         # local dev parity
├── render.yaml                # Render Blueprint — one-click deploy
├── fly.toml                   # Fly.io app config
├── mcp.json                   # MCP Inspector preset
├── server.json                # MCP Registry metadata
├── .github/
│   └── workflows/
│       └── publish-mcp.yml    # registry publish on version tags
├── .dockerignore
├── .gitignore
├── asgi.py                    # production ASGI entrypoint
├── env.example                # all env vars with safe defaults
├── pyproject.toml             # hatchling build, ruff lint
├── README.md
└── DEPLOYMENT.md              # Render / Railway / Fly.io / Docker deploy guide
```

## Included infrastructure

| Module | What it provides |
|--------|-----------------|
| `core/auth.py` | `extract_bearer_token(ctx)` — forward Bearer token verbatim to your backend |
| `core/http_client.py` | `api_get`, `api_post`, `api_patch`, `api_put`, `api_delete`, `api_upload` — pooled httpx client with tenacity retry |
| `core/errors.py` | `MyProjectError` + Auth, Forbidden, Validation, Backend, RateLimit subclasses |
| `core/telemetry.py` | Rotating JSONL log, user IDs hashed via HMAC-SHA256 (`TELEMETRY_HASH_SALT`) |
| `core/handlers.py` | `@tool_handler` — catches errors, formats responses, records telemetry |
| `middleware/auth.py` | CORS → Auth → optional backend token probe on MCP connect (reuses pooled client) |
| `middleware/telemetry.py` | Connection-level events (auth failures, rate limits, MCP connects) |
| `views/` | Health, OAuth discovery (RFC 8414 + 9728), landing page — each in its own file |
| `Dockerfile` | Multi-stage build, non-root `app` user, healthcheck, `WORKERS` env |

Nothing is forced on you. Delete what you don't need.

## Adding a tool

Quickest path:

```bash
remote-mcp add tool search
```

Then mount it in `src/server.py`:

```python
from src.tools.search import search_router
mcp.mount(search_router)
```

Or write one by hand:

```python
# src/tools/my_tool.py
from fastmcp import Context, FastMCP
from src.core.handlers import get_client_and_token, tool_handler

my_router = FastMCP("my-tool")

@my_router.tool()
@tool_handler
async def my_tool(param: str, ctx: Context) -> str:
    client, auth_header = await get_client_and_token(ctx)
    response = await client.get("/some/endpoint", headers={"Authorization": auth_header})
    return response.json()
```

## Sources

Generate tools from what you already have — an OpenAPI spec or a database — instead of writing them by hand.

### From an OpenAPI spec

```bash
pip install 'remote-mcp[openapi]'
remote-mcp add openapi https://api.example.com/openapi.json --tag orders
```

| Flag | Purpose |
|------|---------|
| `--project-dir / -p PATH` | Target project (default `.`) |
| `--name TEXT` | Source name / package dir (default: derived from spec title) |
| `--include GLOB` (repeatable) | Select operations by operationId glob |
| `--exclude GLOB` (repeatable) | Drop operations by operationId glob |
| `--tag TAG` (repeatable) | Select whole OpenAPI tag(s) |
| `--yes / -y` | Non-interactive; requires `--include` or `--tag` |

On a TTY without selection flags, an interactive numbered picker (e.g. `1,3-5` or `all`) opens (operations grouped by tag). Each selected operation becomes one typed tool under `src/tools/<name>/`, with a generated test file alongside it. The command prints the exact lines to add to `src/server.py` to mount the new router — same pattern as `add tool`.

### From a database

```bash
pip install 'remote-mcp[db]'
remote-mcp add database postgresql://user:pass@host/db --include "orders*"
```

| Flag | Purpose |
|------|---------|
| `--project-dir / -p PATH` | Target project (default `.`) |
| `--include GLOB` (repeatable) | Select tables by name glob |
| `--exclude GLOB` (repeatable) | Drop tables by name glob |
| `--schema NAME` | DB schema (driver default if unset) |
| `--allow-write TABLE:OP` (repeatable) | Opt in to a write tool; `OP` is `insert` or `update` |
| `--yes / -y` | Non-interactive; requires `--include` |

**API tools act as the caller; database tools act as the server.** OpenAPI tools forward the caller's Bearer token, so the backend enforces the caller's own permissions. Database tools run with the server's own `DATABASE_URL` credentials — anyone who can call the MCP server can read everything the allowlist exposes. That's why tools are read-only by default: an empty allowlist exposes nothing, and every write is a separate, individually named, opt-in tool (`insert_orders`, `update_orders_by_id`, ...) enabled only via `--allow-write TABLE:OP`. There is no generic `run_sql` tool and there never will be — a free-form query tool is a prompt-injection exfiltration pump.

The DSN is used only at generation time, to introspect the schema — it is never written to any file. The generated `src/tools/db/db.py` reads `DATABASE_URL` (plus `DB_MAX_ROWS`, default 200, and `DB_STATEMENT_TIMEOUT_MS`, default 5000) from the environment at runtime. `add database` appends these three keys to `env.example` (only if the file exists and doesn't already have them) as a reminder to set them in the deploy environment.

### Staying current

Every `add openapi` / `add database` run writes `sources.lock.json` at the project root: what was selected, the spec/schema state it came from, and a content hash per generated file. `remote-mcp doctor` reads it back and reports:

| Check | Needs `--refresh` |
|-------|--------------------|
| Manifest present and parseable | no |
| Generator version vs. installed `remote-mcp` | no |
| Generated files present / locally modified | no |
| Spec/schema drift vs. the live source | yes (network/DB access) |

```bash
remote-mcp doctor --project-dir . --refresh --json
```

Exit codes: `0` clean, `1` drift found, `2` error. `--json` emits machine-readable output for CI. Credential-bearing DSNs (postgres, mysql) can't be re-checked live — the manifest only ever stores a sanitized DSN with credentials stripped — so `--refresh` reports those sources `unreachable` rather than guessing; sqlite and other credential-free DSNs refresh normally. To pick up real drift, re-run the same `add` command: it's idempotent per source name and regenerates the files without touching anything outside the generated set.

### How this differs from FastMCP's runtime OpenAPI integration

FastMCP can proxy an OpenAPI spec at runtime — no generation step, but also no code you can read, patch, or grep. `remote-mcp add openapi` generates code you own: typed tool functions with generated tests, deployed through the same rail as the rest of the scaffold, with zero runtime coupling back to either the spec or this package. Nothing calls out to re-parse the spec on every request; you regenerate when you choose, and you can audit every line remote-mcp ever wrote.

## Connecting to Claude

**Claude.ai (web):** Settings → Connectors → Add → Custom → Web
- URL: `https://your-server.example.com/mcp`

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "my-project": {
      "command": "npx",
      "args": ["-y", "mcp-remote@latest", "https://your-server.example.com/mcp"]
    }
  }
}
```

**Claude Code:**
```bash
claude mcp add my-project --transport http https://your-server.example.com/mcp
```

## Local debugging with MCP Inspector

The scaffold ships an `mcp.json` preset:

```bash
npx @modelcontextprotocol/inspector --config ./mcp.json
```

Set a Bearer token in the Inspector UI to exercise authenticated tools without standing up a full OAuth flow. For zero-config local dev (no token needed), run with `AUTH_MODE=none`.

## Deployment

### Docker / Compose

```bash
docker build -t my-project .
docker run --rm -p 8001:8001 --env-file .env my-project
# or
docker compose up --build
```

### One-click platforms

The generated project ships pre-filled config:

- **Render** — `render.yaml` Blueprint; click the Deploy to Render button in your repo README.
- **Fly.io** — `fly.toml`; run `fly launch --copy-config && fly deploy`.
- **Railway** — Dockerfile-based; point Railway at the repo.

`DEPLOYMENT.md` in the generated project covers env vars, workers, healthcheck, and hardening notes.

## Publish to the MCP Registry

Every scaffolded project ships `server.json` (MCP Registry metadata) and `.github/workflows/publish-mcp.yml` (OIDC-authenticated publish workflow). To list your server on the official registry:

1. Edit `server.json`: replace `YOUR-DOMAIN` with your deployed domain and set `github_owner` to your GitHub user/org.
2. Ensure the server is publicly reachable at the URL in `remotes[].url`.
3. Push a version tag: `git tag v1.0.0 && git push --tags`.

The workflow authenticates via GitHub OIDC (no stored secrets) and publishes to `registry.modelcontextprotocol.io`, which feeds the discovery catalogues that MCP clients use.

## Configuration

Copy `env.example` to `.env` and edit. Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `API_BASE_URL` | `https://api.example.com` | Your upstream API |
| `AUTH_MODE` | `passthrough` | none \| passthrough \| jwt — auth enforcement mode |
| `OAUTH_JWKS_URL` | `` | JWKS URL, required when AUTH_MODE=jwt |
| `JWT_AUDIENCE` | `` | JWT audience; defaults to MCP_PUBLIC_URL |
| `MCP_PUBLIC_URL` | `http://localhost:8001/mcp` | Public MCP URL (shown in landing page) |
| `OAUTH_ISSUER_URL` | `http://localhost:8001` | OAuth issuer for RFC 8414 discovery |
| `OAUTH_AUTHORIZE_PATH` | `/o/authorize/` | OAuth authorize endpoint (relative or full URL) |
| `OAUTH_TOKEN_PATH` | `/o/token/` | OAuth token endpoint |
| `OAUTH_REGISTRATION_PATH` | `/o/register/` | Dynamic client registration endpoint |
| `OAUTH_SCOPES_SUPPORTED` | `read` | Comma-separated scope list |
| `AUTH_PROBE_ENABLED` | `false` | Validate token against backend on MCP connect |
| `AUTH_PROBE_PATH` | `/health/` | Endpoint used for token probe |
| `LOGO_URI` | `` | Logo shown in OAuth discovery (optional) |
| `ALLOWED_ORIGINS` | `https://claude.ai,...` | CORS origins; unset = all origins accepted (startup warning emitted) |
| `TELEMETRY_ENABLED` | `true` | Enable JSONL telemetry |
| `TELEMETRY_HASH_SALT` | `` | HMAC salt for user-id hashing (set per-deployment) |
| `SUPPORT_EMAIL` | `` | Shown as `Get Help` mailto link on the landing page; hidden when unset |

Full variable list and deploy instructions in `DEPLOYMENT.md`.

## How it works

`remote-mcp` renders Jinja2 templates into your project directory at scaffold time. After that, it's gone — no version pinning, no update command, no hidden runtime. You own every line.

## Requirements

- Python ≥ 3.10 (this CLI). Generated project supports the same range.
- FastMCP ≥ 3.0 (installed in the generated project, not this package).

## Contributing

See [CONTRIBUTING.md](https://github.com/pushpendra-tripathi/remote-mcp/blob/main/CONTRIBUTING.md). Security reports: [SECURITY.md](https://github.com/pushpendra-tripathi/remote-mcp/blob/main/SECURITY.md).

## Changelog

See [CHANGELOG.md](https://github.com/pushpendra-tripathi/remote-mcp/blob/main/CHANGELOG.md).

## License

MIT — see [LICENSE](https://github.com/pushpendra-tripathi/remote-mcp/blob/main/LICENSE).
