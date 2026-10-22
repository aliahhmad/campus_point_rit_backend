# Wallet initialization during account creation

Campus calls Points directly whenever `UserManager.register` creates an account.
This covers both public registration and CLI account creation.

1. Campus inserts the user in its current database transaction and gets the ID.
2. Campus calls `PUT /internal/wallets/{user_id}/initialize` and waits.
3. Points creates the wallet and its 100-point `opening_grant` ledger entry
   together in one local transaction.
4. Once Points confirms success, Campus completes registration and commits
   the user. The registration endpoint commits before returning success.

If Points is unavailable or rejects the call, registration returns HTTP 503
and rolls back the new Campus user. Retrying registration is then possible.
Points initialization is idempotent: repeating it for an existing wallet
preserves its current balance and never issues a second opening grant.

The two services have separate commits. Full crash recovery across both
databases belongs to the planned distributed transaction implementation.

## Setup

Set `POINTS_SERVICE_TOKEN` in `backend/.env` to a randomly generated value:

```sh
openssl rand -hex 32
```

Campus and Points use the same value for the internal `X-Service-Token` header.
Keep it out of Git and frontend configuration. Compose passes it to both APIs.

From `backend/`, rebuild and start the services:

```sh
docker compose up --build -d --wait
```

Startup applies Points migration `points_0003`, which enforces one opening
grant per user. Existing accounts in this workspace have already been funded
once. No startup scan or backfill command is needed.

## Profile points and reputation

The frontend's **My profile** page shows the current available balance and
reputation in **My points and reputation**. It loads both when the page opens
and provides a **Refresh** button. Wallet failures show a retry action without hiding
the rest of the profile.

The browser calls authenticated `GET /wallet/me` in Campus. Campus derives the
user ID from the session and calls `GET /internal/wallets/{user_id}` in Points
using `X-Service-Token`. The response contains `user_id`, `available_points`, and
`reputation`.
The browser never receives the internal service token. These GET endpoints
only read existing wallets; they do not create wallets or issue opening grants.

## Verify existing wallets

Open Points PostgreSQL:

```sh
docker compose exec points-db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

At the PostgreSQL prompt:

```sql
SELECT user_id, available_points, reputation FROM wallets ORDER BY user_id;

SELECT user_id, COUNT(*) AS grants, SUM(amount) AS granted_points
FROM points_transactions
WHERE type = 'opening_grant'
GROUP BY user_id
ORDER BY user_id;
```

Each initialized user should have one opening grant totaling 100 points.
Use `\q` to exit PostgreSQL.
