# Installation

The supported development path is the four-service Docker Compose setup. Follow
[quick start](../quick-start.md) for environment creation, migrations, location
import, and startup. A frontend checkout is separate from these backend services.

## Prerequisites

- Docker with Compose and a running Docker runtime.
- Python 3.10–3.14 and `uv` for optional host development and documentation tools.
- Two PostgreSQL databases with prepared transactions enabled when running
  outside Compose. Compose supplies PostgreSQL 18.1 with the required setting.

The backend repository is
[aliahhmad/rit_csci_652_dist_project](https://github.com/aliahhmad/rit_csci_652_dist_project).
Run backend commands from the directory containing `pyproject.toml` and
`docker-compose.yml`.

## Dependencies

```sh
uv sync --locked
```

This installs the project and its default development tools into `.venv` using
`uv.lock`. Use `uv run` for Python commands to avoid relying on global packages.
Docker builds install dependencies from the same lockfile.

See [configuration](configuration/environment.md),
[host development](../development/local.md), and
[container development](../development/docker.md) for the appropriate runtime.
