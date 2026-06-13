# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in runloq, please report it responsibly via GitHub's private security advisory feature instead of the public issue tracker.

**Report here:** [GitHub Security Advisories](https://github.com/runloq/runloq/security/advisories/new)

We appreciate detailed reports (affected code, impact, reproduction steps if possible) and will acknowledge receipt within 48 hours.

## Security Architecture

### Local-First Design

runloq is **built for local use by default**:

- **No authentication required** for CLI or local dashboard (loopback-only by design)
- SQLite database and config file are local files
- All network bindings default to `127.0.0.1` (loopback-only)

### Dashboard Security

The dashboard API has **no built-in authentication** — it is not designed for multi-user or remote deployment out of the box. For production deployments:

- **Only expose via a reverse proxy** (nginx, Caddy) with external authentication
- **Enable the optional API token** by setting `RUNLOQ_API_TOKEN` env var (recommended for any remote access)
- See the [README Security section](./README.md#security) for detailed guidance on token setup and remote deployment patterns

### Data Protection

- **Secrets are never logged**: tokens and API keys are redacted in audit trails
- **SQL injection is prevented**: all database queries use parameterized bindings
- **XSS in the dashboard is prevented**: react-markdown renders HTML-escaped by default (no raw HTML injection)
- **Config portability**: sensitive paths are resolved relative to the config file; no hardcoded absolute paths

### Docker & Network

If running runloq in Docker:

- **Never bind to `0.0.0.0`** — this exposes the unauthenticated dashboard to the network
- Default `docker-compose.yml` binds to `127.0.0.1:3002:3002` (loopback-safe)
- Always use a reverse proxy and enable the API token for any remote access

## Scope of Coverage

Security vulnerabilities in runloq itself (code, config, schema) are in scope. Third-party dependencies are managed via `pip-audit` in CI; please check there first or report supply-chain concerns directly.

## Release Updates

Follow this repository's releases on GitHub to stay updated with security fixes.
