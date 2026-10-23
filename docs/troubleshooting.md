# Troubleshooting and database inspection

| Symptom | Check |
| --- | --- |
| Campus exits with the documentation warning | Add `I_READ_THE_DAMN_DOCS=true` to `.env` and recreate the API container |
| Registration returns 503 | Points availability, shared service token, and Points database initialization |
| Location dropdown is empty or creation reports `invalid_location` | Import the CSV and confirm the selected location is active |
| Request creation reports `insufficient_points` | Available wallet balance must cover the fixed five-point hold |
| A new request or response is hidden | Check `MODERATION_BLOCKED_WORDS`; blocked matches intentionally return `hidden` |
| Moderation remains pending | Inspect the Campus moderation error log; pending means the check failed |
| Operation remains processing | Both API/database health checks, recorded decision, participant acknowledgements, recovery logs, and native preparations |
| Preparation fails with service unavailable | Confirm `max_prepared_transactions` is nonzero in both databases and the service token matches |
| Browser reports CORS errors or email links use the wrong host | Set `CORS_ORIGINS` and `FRONTEND_URL`, then recreate the affected API service |
| Database credentials changed but the database rejects them | Existing PostgreSQL volumes retain their initialized users/passwords; changing `.env` alone does not alter database roles |
| A request expired while Campus was stopped | Startup scanning processes it; allow for scan batches, service availability, and recovery time |

## Inspect stored state

Open Campus PostgreSQL:

```sh
docker compose exec campus-db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

Run SQL at the PostgreSQL prompt:

```sql
SELECT id, requester_id, title, status, moderation_status,
       expires_at, accepted_response_id
FROM requests
ORDER BY id DESC;

SELECT id, request_id, contributor_id, moderation_status, answer
FROM responses
ORDER BY id DESC;

SELECT id, operation, owner_id, request_id, response_id,
       state, decision, error_code
FROM distributed_transactions
WHERE state <> 'finished'
ORDER BY created_at;

SELECT transaction_id, participant, vote, acknowledged
FROM transaction_participants
ORDER BY transaction_id, participant;
```

Open Points PostgreSQL separately:

```sh
docker compose exec points-db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

```sql
SELECT user_id, available_points, reputation FROM wallets ORDER BY user_id;

SELECT request_id, requester_id, amount, status,
       recipient_id, awarded_response_id
FROM escrows
ORDER BY request_id;

SELECT user_id, type, amount, distributed_transaction_id, created_at
FROM points_transactions
ORDER BY created_at DESC;
```

In either database, inspect native preparations and local journals:

```sql
SHOW max_prepared_transactions;

SELECT gid, prepared, owner, database
FROM pg_prepared_xacts
WHERE database = current_database();

SELECT transaction_id, operation, state, updated_at
FROM participant_transactions
ORDER BY updated_at DESC;
```

Exit `psql` with `\q`. For stuck operations, inspect the saved decision and
service logs, then restore database/service connectivity so recovery can finish.
Do not manually roll back a prepared transaction just because it is old: its
coordinator may already have committed the global decision.
