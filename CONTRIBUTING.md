# Contributing to CampusPoint

Use this project's repository and documentation when proposing changes. The
backend extends an upstream FastAPI foundation, but CampusPoint's requests,
Points service, transaction protocol, and recovery require project-specific
review and validation.

## Development setup

Follow [quick start](docs/quick-start.md) and use `uv sync --locked` for host
tools. Keep changes focused and preserve existing application data. Additions
that change schemas need the correct Campus or Points Alembic migration.

## Transaction rules

- Each service owns and accesses only its own database.
- Native preparations use dedicated connections and durable participant journals.
- Record a decision only after collecting votes; never replace a saved decision.
- Finish COMMIT as COMMIT even after a timeout, deadline, or lost reply.
- Preserve original payload hashes and operation IDs across retries/recovery.
- Derive financial identities and amounts on the server.
- Lock requests/escrows/wallets consistently and preserve ledger uniqueness.
- A confirmed abort remains aborted; a fresh business attempt gets a new key.
- Use guarded settlement APIs rather than direct balance or status edits.

Read [2PC](docs/development/two-phase-commit.md) and
[recovery](docs/development/recovery.md) before changing those paths.

## Validation

```sh
uv run python -m pytest tests_requests tests_points -o addopts='' -q
uv run python -m ruff check app tests_requests tests_points tests_workflow
uv run python -m ruff format --check app tests_requests tests_points tests_workflow
uv run python -m pymarkdown scan -r docs
uv run python -m mkdocs build --strict
```

For changes to distributed behavior, run `tests_workflow` against two disposable
PostgreSQL databases with prepared transactions enabled. Fixtures truncate data
and resolve test preparations: never use development/demo or production URLs.
The original `tests/` suite also drops/recreates its `TEST_DB_NAME` schema.
See [testing](docs/development/testing.md) for environment and commands.

## Review information

Describe the concrete behavior changed, schema/configuration impact, relevant
failure or retry behavior, and checks actually run. Update API contracts and
examples with implementation changes. Do not claim unrun test counts or coverage.

Preserve [license notices](LICENSE.txt) and the [code of conduct](CODE_OF_CONDUCT.md).
Report sensitive findings privately as described in [SECURITY.md](SECURITY.md).
