# Databases and migrations

Campus and Points own separate PostgreSQL databases and separate Alembic
histories. There are no cross-service foreign keys. The development Compose
stack starts PostgreSQL 18.1 with `max_prepared_transactions=100` on both services.

| Connection | Campus | Points |
| --- | --- | --- |
| Host tools | `localhost:5433` | `localhost:5434` |
| API containers | `campus-db:5432` | `points-db:5432` |
| Credentials/settings | `DB_*` | `POINTS_DB_*` |
| Migration config | `alembic.ini` | `alembic-points.ini` |

Compose supplies container connection addresses. For host tools, set the
corresponding loopback ports in `.env`.

## Apply migrations

For running APIs:

```sh
docker compose exec campus-api alembic upgrade head
docker compose exec points-api alembic -c alembic-points.ini upgrade head
```

API startup also runs these migrations automatically. Schema creation does not
load locations; follow [the CSV import](../../development/locations.md).

## Prepared transactions

```sql
SHOW max_prepared_transactions;
SELECT gid, prepared, database
FROM pg_prepared_xacts
WHERE database = current_database();
```

A value of zero disables native preparation. Changing it requires restarting
PostgreSQL. Do not manually roll back an old preparation without checking the
coordinator decision; restore service connectivity and let recovery resolve it.

## Persistence and testing

Named volumes retain data across `docker compose down`. Using `down -v` deletes
both application databases. Existing PostgreSQL roles/passwords are initialized
in the volume; changing environment variables does not alter those roles.

Tests must use disposable databases. The original `tests/` suite uses
`TEST_DB_NAME`; cross-service tests use two explicitly supplied test URLs.
Both can remove stored test data. See [testing](../../development/testing.md).
