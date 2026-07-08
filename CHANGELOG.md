# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-07-06

remote-mcp 1.0: from scaffolder to source-connected generator. The CLI
surface is now stable — breaking CLI changes require a major bump.

### Added
- `remote-mcp add openapi <SPEC>`: selected OpenAPI 3.x operations become
  typed MCP tools with auth pass-through, error mapping, and generated tests.
  Interactive picker on TTY; `--include` / `--exclude` / `--tag` globs and
  `--name` for CI and naming. Requires `pip install 'remote-mcp[openapi]'`.
- `remote-mcp add database <DSN>`: introspected schema becomes read-only
  query tools (`list_<table>` / `get_<table>_by_<pk>` / `search_<table>`) with
  allowlist enforcement (`--include` / `--exclude` / `--schema`), row caps,
  statement timeouts, and generated tests. Writes are per-table, per-operation
  opt-in via `--allow-write TABLE:OP` (`insert`, `update`) — never a global
  flag, and there is no generic `run_sql` tool. DSN is used only at
  generation time and never written to any file. Requires
  `pip install 'remote-mcp[db]'`.
- `sources.lock.json`: manifest of every generated source — what was
  selected, from which spec/schema state, per-file content hashes.
- `remote-mcp doctor`: drift report (local modifications, missing files,
  generator-version drift, and with `--refresh` live source drift).
  Exit codes: 0 clean, 1 drift, 2 error. `--json` for CI.
- `env.example` in database-enabled projects gains `DATABASE_URL`,
  `DB_MAX_ROWS`, and `DB_STATEMENT_TIMEOUT_MS` (appended by `add database`
  when the file exists and doesn't already have them).

### Security
- Database tools carry a documented threat-model boundary: API tools act as
  the caller (Bearer pass-through); database tools act as the server
  (server-side credentials). Read-only by default, empty allowlist exposes
  nothing, no generic run_sql tool is ever generated. The manifest stores
  only a sanitized DSN (credentials stripped); postgres/mysql DSNs typically
  report `unreachable` under `doctor --refresh` because stored locators have
  credentials stripped — credential-free DSNs (sqlite) refresh normally.

## [0.3.0] — 2026-06-15

### Added
- `AUTH_MODE` setting in generated projects: `none` (local dev, no auth), `passthrough` (default, current behavior), `jwt` (local verification against `OAUTH_JWKS_URL`; new `verify_jwt()` in `core/auth.py`, `pyjwt[crypto]` dependency).
- `--auth-mode`, `--github-owner`, `--legacy-sse` flags on `remote-mcp new`.
- Registry readiness: generated `server.json` (2025-12-11 schema) and `.github/workflows/publish-mcp.yml` publishing to registry.modelcontextprotocol.io on version tags.
- Origin validation per MCP spec 2025-11-25: disallowed `Origin` headers get 403.
- 401 responses now carry `WWW-Authenticate: Bearer resource_metadata="…"` (RFC 9728) so clients can discover the authorization server.
- Example echo tool is mounted by default — fresh scaffolds expose a working tool on first boot.
- Startup warning when `ALLOWED_ORIGINS` is unset (all origins accepted; warning makes the permissive posture visible in logs).

### Changed
- **MCP endpoint moved from `/sse` to `/mcp`** (Streamable HTTP, per spec). `--legacy-sse` opts into a deprecated SSE transport alias at `/sse`.
- MCP Inspector preset (`mcp.json`) now declares `streamable-http`.
- CORS configuration exposes `mcp-session-id` and allows `mcp-protocol-version` headers (required by browser-based clients).
- `.github/` directory now supported in scaffold output (segment-level dot renames).

### Fixed
- JWKS and backend-probe error responses no longer echo the raw exception string to HTTP clients; detail is logged server-side only.
- `verify_jwt` type hints corrected: `signing_key: bytes | None`, return `dict[str, Any]`.
- JWT and JWKS imports hoisted to module top in auth middleware template (were inside dispatch body, triggering linter warnings).

## [0.2.1] — 2026-06-03

### Added
- One-click deploy templates: `render.yaml`, `fly.toml`, `docker-compose.yml` in scaffolded project.
- `mcp.json` preset for MCP Inspector (`npx @modelcontextprotocol/inspector --config ./mcp.json`).
- `SUPPORT_EMAIL` env var wired into landing-page `Get Help` link (hidden when unset).
- `Releases` and `Documentation` URLs on PyPI sidebar.
- `pip-audit` security job in CI (runs on every push/PR).
- `pytest-timeout` and `ruff` added to root `[project.optional-dependencies.dev]`.
- README + ROADMAP refreshed for v0.2.0 changes; `docs/ROADMAP.md` published.

### Changed
- Project-name validator now enforces minimum length of 2 chars (regex previously allowed 1).

### Fixed
- Windows CI: tests read generated files with explicit `encoding="utf-8"` (was failing on cp1252 locale when files contained em-dashes / smart quotes).
- Repository formatting reflowed via `ruff format`.

## [0.2.0] — 2026-06-03

### Added
- `remote-mcp add tool <name>` subcommand to scaffold a new tool stub.
- `--yes / -y`, `--service-name / -s`, `--into` flags on `remote-mcp new`.
- Project-name and tool-name validation (kebab/snake regex, Python keyword check).
- `python -m remote_mcp` entry point (`__main__.py`).
- `Dockerfile` and `.dockerignore` in scaffolded projects.
- Configurable OAuth endpoint paths (`OAUTH_AUTHORIZE_PATH`, `OAUTH_TOKEN_PATH`, `OAUTH_REGISTRATION_PATH`).
- `TELEMETRY_HASH_SALT` for HMAC-salted user-id hashing.
- E2E test that scaffolds + installs + runs the generated test suite.
- Ruff configuration in both the package and the scaffolded template.
- CI matrix expanded to Python 3.10–3.13 and macOS/Windows smoke jobs.

### Changed
- Python floor lowered from 3.12 to 3.10.
- Scaffolded project uses Hatchling (was setuptools); Ruff replaces Pylint.
- `auth.RequireAuthMiddleware` reuses the pooled `httpx.AsyncClient` for the SSE handshake probe.
- `Settings` access is now lazy via `get_settings()`; no import-time side effects.
- `format_error` no longer leaks unknown-exception strings to MCP clients; logs full detail.
- `http_client.py` retry logic deduplicated via a single `_request_with_retry` helper.
- `__version__` is now read from installed package metadata.

### Fixed
- Health/well-known/asset path bypass tightened (no longer matches `/healthcheck-leaky`).
- Removed dead `Authorization` (TitleCase) header lookup branch (Starlette headers are case-insensitive).
- OIDC discovery payload no longer impersonates OAuth-2.0 metadata.

## [0.1.2] — 2026-06-02

- Version bump only.

## [0.1.1] — 2026-05-31

- Split `server.py` monolith into `app.py` / `views/` / `middleware/` layers.

## [0.1.0] — 2026-05-31

- Initial release.
