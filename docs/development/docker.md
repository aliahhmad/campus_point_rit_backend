# Develop with Docker

CampusPoint now uses four containers: `campus-api`, `points-api`, `campus-db`,
and `points-db`. The previous template service names `api`, `db`, and `cache`
are no longer part of the main Compose file.

From `backend/`, run:

```sh
colima start
docker compose up --build -d --wait
docker compose ps
```

Campus API documentation: <http://localhost:8001/docs>.
Points API documentation: <http://localhost:8003/docs>.

The [CampusPoint development guide](campuspoint.md) explains environment
configuration, networks, existing data, where to add APIs, and how to create
PostgreSQL tables using each service's Alembic migrations.
