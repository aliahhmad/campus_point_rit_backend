# Host development

Compose is the simplest complete setup. To run API processes on the host while
keeping its PostgreSQL containers, first stop the container API processes so
ports are free and duplicate expiry/recovery workers are avoided:

```sh
docker compose stop campus-api points-api
docker compose up -d --wait campus-db points-db
uv sync --locked
```

Set `.env` with host connections (`DB_ADDRESS=localhost`, `DB_PORT=5433`,
`POINTS_DB_ADDRESS=localhost`, `POINTS_DB_PORT=5434`), generated secrets,
`I_READ_THE_DAMN_DOCS=true`, `POINTS_API_URL=http://localhost:8003`, and
`POINTS_CAMPUS_API_URL=http://localhost:8001`. Include Campus's `API_ROOT` in
that last URL when configured.

Apply both migration histories:

```sh
uv run alembic upgrade head
uv run alembic -c alembic-points.ini upgrade head
```

Import [locations](locations.md) for a fresh Campus database. Start Points in one
terminal, then Campus in another:

```sh
uv run uvicorn app.points.main:app --host 127.0.0.1 --port 8003 --reload
```

```sh
uv run uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

Both applications start their lifespan workers automatically. The legacy
`api-admin serve` command starts only Campus and defaults to port 8000; it does
not launch Points. Prefer the explicit commands above for this project.

Run [isolated and PostgreSQL workflow tests](testing.md) with separate disposable
databases. Do not point destructive test fixtures at the running application's
data.
