# Load campus locations before starting the application

The location list is bundled at `backend/app/database/rit_locations.csv`.
It contains 103 rows with the columns `id`, `name`, and `code`.

Load this data during first-time setup, after creating the Campus database
tables and before starting the APIs and frontend. The database container must
be running so the migration and import can connect to PostgreSQL.

The import maps `name` to `locations.name` and `code` to
`locations.building_code`. PostgreSQL generates the location IDs; the CSV IDs
are ignored. `is_active` defaults to `true`. There is no URL field.

## 1. Start the Campus database and apply migrations

Configure `backend/.env` with your database credentials, JWT secret, Points
database password, and `I_READ_THE_DAMN_DOCS=true` as part of the normal project
setup. Keep an existing configured `.env` when updating the project.

Open your IDE terminal. From the main `Project` folder, enter the backend:

```sh
cd backend
```

Skip `cd backend` if your terminal is already there. Run these commands in your
normal terminal, where the prompt ends in `%` or `$`:

```sh
colima start
docker compose up -d --wait campus-db
docker compose run --build --rm --no-deps campus-api alembic upgrade head
```

The last command runs migrations in a temporary API container. It creates the
`locations` table and exits. The migration creates the schema; the CSV import
below supplies the rows. Applying the migration again leaves an up-to-date
database unchanged.

## 2. Copy the CSV into the database container

Still in the normal terminal, from `backend/`, run:

```sh
docker cp app/database/rit_locations.csv campuspoint-campus-db:/tmp/rit_locations.csv
```

This copies the CSV from your backend checkout into the database container.
Repeat this command if the container has been recreated or the CSV has changed.

## 3. Open PostgreSQL

Run this in the normal terminal:

```sh
docker compose exec campus-db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

The prompt changes from your normal shell to the PostgreSQL prompt, for example:

```text
campuspoint_campus=#
```

Run the next commands inside this PostgreSQL session. The temporary table
exists only in this session, so keep it open until the import is complete.

## 4. Create a temporary import table

Paste this SQL into PostgreSQL:

```sql
BEGIN;

CREATE TEMP TABLE location_import (
    csv_id INTEGER,
    name TEXT,
    code TEXT
) ON COMMIT DROP;
```

## 5. Read the CSV

Run this command separately, on its own line in PostgreSQL:

```text
\copy location_import FROM '/tmp/rit_locations.csv' WITH (FORMAT csv, HEADER true)
```

Expected output:

```text
COPY 103
```

Continue only after the copy succeeds. `\copy` is a PostgreSQL client command;
running it at the normal `%` or `$` shell prompt can produce a zsh error.

## 6. Insert and verify the locations

Paste this SQL into the same PostgreSQL session:

```sql
INSERT INTO locations (name, building_code)
SELECT name, code
FROM location_import
ON CONFLICT (building_code) DO NOTHING;

COMMIT;

SELECT COUNT(*) FROM locations;

SELECT id, name, building_code, is_active
FROM locations
ORDER BY id
LIMIT 10;
```

For an initially empty table, the count should be **103**. Existing building
codes are skipped when repeating the import, so rerunning it does not create
duplicates. Existing rows keep their names and active status. Updating existing
location details requires a separate update.

The insert runs in a transaction. If the prompt contains `!`, such as
`campuspoint_campus=!#`, a command has failed. Enter `ROLLBACK;`, fix the reported
problem, and repeat steps 4 through 6. Check that every SQL statement ends
with a semicolon and that `\copy` is entered on its own line. If the CSV file
cannot be found, repeat step 2 from another normal terminal first.

Exit PostgreSQL after a successful import:

```text
\q
```

Your normal terminal prompt returns.

## 7. Start the application

From the normal terminal in `backend/`, start all four containers:

```sh
docker compose up --build -d --wait
docker compose ps
```

Then start the frontend from a separate terminal in the main `Project` folder:

```sh
cd frontend
npm install
npm run dev
```

Campus API documentation is at <http://localhost:8001/docs>; the frontend is
at <http://localhost:5173>. Authenticated `GET /locations` returns active locations for the creation form.

## Later starts

Database volumes retain the imported locations across normal container stops
and starts. Import the CSV once per fresh Campus database, or when adding new
building codes to the bundled list. Normal starts use the commands in step 7.

`docker compose down -v` removes database volumes and their imported data.
Recreating a database requires applying migrations and loading locations again.
