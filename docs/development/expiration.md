# Automatic request expiry

Campus scans requests as soon as its background worker starts and then after
each configured interval. It changes `open` and `under_review` requests to
`expired` when `expires_at <= CURRENT_TIMESTAMP`, using the database clock.
It checks all moderation statuses. Completed requests and accepted responses
stay unchanged, and running the scan again is safe.

Set the interval in `backend/.env` using a positive number of seconds:

```dotenv
REQUEST_EXPIRY_SCAN_INTERVAL_SECONDS=60
```

The default is 60 seconds. Restart Campus after changing it. The interval starts
after each scan finishes, so scans in one worker never overlap. Requests that
expire while the API is stopped are picked up on startup. Response submission
and acceptance also check the deadline directly, so they reject expired
requests even before the next scan updates their stored status.

## Transactions and recovery

Expiry changes only the Campus database, so one ordinary PostgreSQL transaction
is enough. A recurring schedule does not itself require two-phase commit. This
scan leaves Points wallets, reputation, escrows, and ledger entries unchanged.
Refunding held rewards would require its own coordinated Campus/Points feature.

The scan locks eligible rows with `FOR UPDATE SKIP LOCKED`. Requests locked by
an in-flight response or acceptance transaction are skipped until a later scan,
so expiry cannot overwrite a prepared or completed acceptance or interrupt its
recorded 2PC decision. Multiple Campus workers can safely scan concurrently.
Database failures are logged and retried after the interval; shutdown cancels
the worker cleanly. A crash rolls back an unfinished scan, and the next scan
finds any remaining overdue rows.

The implementation is in `app/managers/expiration.py`, started by Campus's
FastAPI lifespan in `app/main.py`. No schema migration is needed.

To inspect the stored status in PostgreSQL:

```sql
SELECT id, title, status, expires_at, accepted_response_id
FROM requests
ORDER BY id DESC;
```
