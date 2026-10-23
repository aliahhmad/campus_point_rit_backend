# Continuous integration

The checked-in workflows under `.github/workflows/` include Ruff checks, mypy,
Prek, dependency review, CodeQL, Zizmor, and the original Python test matrix.
Workflow files are the source of truth for triggers, versions, and services.

The current `tests.yml` runs `pytest tests` with a PostgreSQL service across
Python 3.10–3.14. It does not run `tests_requests`, `tests_points`, or the
CampusPoint cross-service `tests_workflow` suite. It therefore is not evidence
that distributed settlement and recovery have been exercised by CI.

For local validation:

```sh
uv run python -m pytest tests_requests tests_points -o addopts='' -q
uv run python -m ruff check app tests_requests tests_points tests_workflow
```

Real 2PC testing requires two disposable PostgreSQL databases with prepared
transactions enabled and both test URLs configured. See [testing](testing.md).
If adding that suite to CI, provision those databases explicitly and keep them
isolated from development or deployment credentials.

Do not publish coverage percentages or test counts as project guarantees unless
measured on the relevant checkout. Documentation builds are separate from API
deployment and do not automatically regenerate OpenAPI schemas.
