# Develop with Docker

CampusPoint now uses four containers: `campus-api`, `points-api`, `campus-db`,
and `points-db`. The previous template service names `api`, `db`, and `cache`
are no longer part of the main Compose file.

For first-time setup, follow [Load campus locations](locations.md). It starts
the Campus database, applies migrations, and imports the bundled CSV before
starting the APIs and frontend.

For later runs, from `backend/`, run:

```sh
colima start
docker compose up --build -d --wait
docker compose ps
```

Campus API documentation: <http://localhost:8001/docs>.
Points API documentation: <http://localhost:8003/docs>.

The [locations guide](locations.md) includes the import commands, verification,
and help distinguishing the normal terminal from the PostgreSQL prompt.
