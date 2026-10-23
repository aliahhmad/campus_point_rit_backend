# Migrations and testing

## Schema migrations

Compose runs migrations automatically on API startup. To apply them explicitly
to running services:

```sh
docker compose exec campus-api alembic upgrade head
docker compose exec points-api alembic -c alembic-points.ini upgrade head
```

Campus and Points have separate migration histories. When managing PostgreSQL
outside Compose, enable prepared transactions on both databases before starting
2PC work; a zero `max_prepared_transactions` prevents preparation and changing
that setting requires a database restart.

## Validation and service tests

For local Python tooling, install the locked dependencies, including development
tools:

```sh
uv sync --locked
uv run python -m pytest tests_requests tests_points -o addopts='' -q
```

These suites cover validation, moderation, authorization boundaries, schemas,
and isolated service behavior. By default, request intake tests use temporary
SQLite and Points tests mock their database. They do not prove native 2PC.

## Real PostgreSQL workflow tests

Create **two disposable PostgreSQL databases**, with prepared transactions
enabled, and supply their URLs explicitly. For example, assuming a dedicated
test server on port 5543 with the following databases already created:

```sh
REQUESTS_TEST_DATABASE_URL='postgresql+asyncpg://test_user:test_password@127.0.0.1:5543/campus_test' \
POINTS_TEST_DATABASE_URL='postgresql+asyncpg://test_user:test_password@127.0.0.1:5543/points_test' \
uv run python -m pytest tests_workflow -o addopts='' -q
```

**Workflow fixtures truncate application tables and roll back test preparations.
Never point these variables at development/demo data or production databases.**
The URLs must identify different databases. Without both variables, workflow
fixtures skip their database-dependent tests.

Workflow coverage includes creation, response visibility, wallet conservation,
reward/reputation and refund accounting, permissions, competing settlements,
idempotent retries, local rollback, lost prepare/commit acknowledgements, and
crash recovery. These tests exercise native prepared transactions through both
services' ASGI routes.

The original `tests/` suite uses `TEST_DB_NAME` and drops/recreates its schema.
Configure that database separately before running it; do not use the application
database for this suite either.

Useful code and documentation checks:

```sh
uv run python -m ruff check app tests_requests tests_points tests_workflow
uv run python -m ruff format --check app tests_requests tests_points tests_workflow
uv run python -m pymarkdown scan README.md
```
