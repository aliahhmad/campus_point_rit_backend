# Quick start

Run commands from the backend checkout. Install Docker with Compose and start
your Docker runtime. On a Colima setup, run `colima start` first.

## 1. Configure the environment

On first setup only:

```sh
cp .env.example .env
```

Keep an existing configured `.env`. Replace the placeholder Campus database
credentials, Points database password, JWT secret, and shared service token.
Generate separate random values with `openssl rand -hex 32`.

Add or update:

```env
I_READ_THE_DAMN_DOCS=true
DB_ADDRESS=localhost
DB_PORT=5433
POINTS_DB_ADDRESS=localhost
POINTS_DB_PORT=5434
BASE_URL=http://localhost:8001
API_TITLE=CampusPoint
FRONTEND_URL=http://localhost:5173
CORS_ORIGINS=http://localhost:5173
```

Set `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `POINTS_DB_NAME`, `POINTS_DB_USER`,
`POINTS_DB_PASSWORD`, `POINTS_SERVICE_TOKEN`, and `SECRET_KEY` in the same file.
Use a different `TEST_DB_NAME` for disposable test data. See
[environment settings](usage/configuration/environment.md).

## 2. Create the schema and import locations

```sh
docker compose up -d --wait campus-db points-db
docker compose run --build --rm --no-deps campus-api alembic upgrade head
```

Follow [the location import commands](development/locations.md) before creating
requests. Migrations do not automatically load the bundled campus CSV.

## 3. Start both APIs

```sh
docker compose up --build -d --wait points-api
docker compose up --build -d --wait campus-api
docker compose ps
```

Each API applies its own migrations at startup. Compose enables prepared
transactions on both databases. Existing database volumes retain their data.

- Campus Swagger: <http://localhost:8001/docs>
- Points Swagger: <http://localhost:8003/docs>
- Campus heartbeat: <http://localhost:8001/heartbeat>
- Points readiness: <http://localhost:8003/ready>

Campus addresses include `API_ROOT` if you configured a prefix.

## 4. Create a demo account

```sh
docker compose exec campus-api api-admin user create
docker compose exec campus-api api-admin user list
```

Use the actual ID printed by the CLI to verify the account and, if needed,
make it an administrator. These examples use ID 1:

```sh
docker compose exec campus-api api-admin user verify 1
docker compose exec campus-api api-admin user admin 1
```

Points must be running during creation because registration initializes the
wallet and its one-time 100-point grant. Verification through the CLI is useful
when SMTP is not configured for a local demo.

## 5. Use the application

Run the separate frontend using its README, or call Campus directly. Login with
`POST /login/`, then send `Authorization: Bearer <access-token>` on protected
requests. The Swagger **Authorize** control can be used to provide credentials.

Request creation, response creation, acceptance, and administrator refunds also
require `Idempotency-Key`. Keep the same key when retrying an uncertain action.
See [API reference](reference/api.md) for the request workflows.

## Stop or update

```sh
docker compose logs --tail=100 -f campus-api points-api
docker compose down
```

Normal shutdown keeps database volumes. `docker compose down -v` deletes them.
After changing `.env`, [recreate the APIs](development/docker.md) so the new
values are loaded. Source updates may require rebuilding the images.
