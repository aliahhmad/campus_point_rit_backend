# Container development

The default stack has `campus-api`, `points-api`, `campus-db`, and `points-db`.
Follow [quick start](../quick-start.md) for the initial `.env` and location import.

```sh
docker compose up --build -d --wait points-api
docker compose up --build -d --wait campus-api
docker compose ps
```

Each API runs its own migrations before starting Uvicorn with development
reload enabled. The source checkout is mounted into API containers; dependencies
live in container environments. Rebuild images after dependency changes.

After changing `.env`, recreate the affected APIs so environment values reload:

```sh
docker compose up -d --force-recreate --wait points-api
docker compose up -d --force-recreate --wait campus-api
```

For logs and normal shutdown:

```sh
docker compose logs --tail=100 -f campus-api points-api
docker compose down
```

Normal shutdown preserves named PostgreSQL volumes. `down -v` deletes them.
Do not delete volumes to resolve a stuck 2PC operation; inspect the recorded
decision and restore service connectivity for recovery.

Host database ports are 5433/5434; container-to-database traffic uses Docker DNS
and port 5432. Public API bindings are loopback-only. See
[databases](../usage/configuration/database.md), [testing](testing.md), and
[deployment](../deployment/deployment.md).
