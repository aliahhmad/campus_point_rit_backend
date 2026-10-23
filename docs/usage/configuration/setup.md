# Install dependencies

For host tools, use Python 3.10–3.14 and the checked-in lockfile:

```sh
uv sync --locked
```

Run tools through the environment:

```sh
uv run python -m pytest tests_requests tests_points -o addopts='' -q
uv run python -m mkdocs serve
```

Configure `.env` first; importing application modules loads settings even when
an API server is not started. Docker installs its own locked dependencies and
does not require a host virtual environment to run the APIs.

Dependency changes belong in `pyproject.toml` and `uv.lock`. Rebuild API images
after changing them. Do not document or install from an untracked
`requirements.txt` as the project's source of dependency versions.

Next: [environment settings](environment.md) and [databases](database.md).
