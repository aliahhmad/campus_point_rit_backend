# Environment settings

On first setup, copy `.env.example` to `.env`. Keep an existing configured file
when updating. Campus loads `DB_*` settings; Points loads `POINTS_*` settings.
Environment variables override values from the file. Never commit real secrets.

## Required setup

| Variable | Purpose |
| --- | --- |
| `I_READ_THE_DAMN_DOCS=true` | Required Campus startup guard |
| `DB_USER`, `DB_PASSWORD`, `DB_NAME` | Campus database identity and name |
| `DB_ADDRESS`, `DB_PORT` | Campus database host and port; host tools use `localhost:5433` |
| `POINTS_DB_USER`, `POINTS_DB_PASSWORD`, `POINTS_DB_NAME` | Separate Points database identity and name |
| `POINTS_DB_ADDRESS`, `POINTS_DB_PORT` | Points connection; host tools use `localhost:5434` |
| `SECRET_KEY` | Generated JWT secret of at least 32 characters |
| `POINTS_SERVICE_TOKEN` | Same nonempty internal HTTP token in both APIs |
| `TEST_DB_NAME` | Separate disposable database for original Campus tests |

Generate separate secrets with `openssl rand -hex 32`. The example placeholders
must be replaced. Compose passes database credentials to its PostgreSQL services
and overrides API connection hosts to Docker DNS and port 5432.

## Service and frontend URLs

| Variable | Example or behavior |
| --- | --- |
| `POINTS_API_URL` | Campus reaches Points at `http://localhost:8003` outside Docker |
| `POINTS_CAMPUS_API_URL` | Points reads decisions at `http://localhost:8001`; include Campus `API_ROOT` if configured |
| `API_ROOT` | Empty by default; optional Campus prefix such as `/v1` |
| `BASE_URL` | Public Campus URL for backend links; set to `http://localhost:8001` locally |
| `FRONTEND_URL` | `http://localhost:5173` locally; public website URL when deployed |
| `CORS_ORIGINS` | Comma-separated frontend origins, including scheme and port |

Compose sets service-network URLs automatically. Browser requests go to Campus;
keep the Points service token and database credentials out of frontend builds.
For a separately hosted frontend, set its `VITE_API_BASE_URL` to the public
HTTPS Campus address and allow its origin through `CORS_ORIGINS`.

## CampusPoint behavior

| Variable | Behavior |
| --- | --- |
| `MODERATION_BLOCKED_WORDS` | Comma-separated, case-insensitive whole-word blocklist for new content; empty approves all content |
| `REQUEST_EXPIRY_SCAN_INTERVAL_SECONDS` | Positive delay after each expiry pass; defaults to 60 seconds |
| `API_TITLE` | Set `CampusPoint` for Swagger, emails, and metrics namespace |
| `API_DESCRIPTION`, `REPOSITORY` | Optional overrides for inherited display metadata |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access token lifetime; defaults to 120 minutes |

Transaction recovery delays are currently fixed at five seconds in each service;
they are independent of the configurable expiry interval. Updating the blocklist
does not change already stored moderation statuses.

## Email and optional infrastructure

Configure `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`,
`MAIL_FROM`, `MAIL_FROM_NAME`, and the `MAIL_*` TLS/credential switches for
verification and reset emails. Set `MAIL_FROM_NAME="CampusPoint RIT"` for the
sender label. A local demo can use CLI verification when SMTP is unavailable.

`ADMIN_PAGES_ENABLED` controls the optional backend SQLAdmin site;
`ADMIN_PAGES_ROUTE`, `ADMIN_PAGES_TITLE`, `ADMIN_PAGES_TIMEOUT`, and
`ADMIN_PAGES_ENCRYPTION_KEY` configure it. This is separate from React admin pages.

`CACHE_ENABLED`, `METRICS_ENABLED`, and `RATE_LIMIT_ENABLED` are disabled by
default. `REDIS_*` settings supply an optional shared cache/rate-limit store.
`LOG_*` settings control log destinations, categories, levels, and retention.
See the dedicated [cache](../caching.md), [metrics](../metrics.md), and
[rate-limit](../rate-limiting.md) guides before enabling them.

## Apply changes

Restart host API processes after changing settings. Under Compose, recreate API
containers to load updated environment values:

```sh
docker compose up -d --force-recreate --wait points-api
docker compose up -d --force-recreate --wait campus-api
```

Database role/password changes require actual PostgreSQL administration when a
volume already exists. Never delete application volumes merely to apply an API
configuration change.
