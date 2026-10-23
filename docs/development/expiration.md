# Automatic expiry, refunds, and conflicts

Campus checks overdue requests on startup and after each configured interval.
The database clock determines whether `expires_at <= CURRENT_TIMESTAMP`.

| Request at its deadline | Result | Points |
| --- | --- | --- |
| No visible responses and no accepted answer | `expired` | Return its held five points to the requester through 2PC |
| One or more visible responses, with no accepted answer | `conflicted` | Keep the reward held for later resolution |
| Completed or already accepted | Unchanged | No refund |

Only responses with `moderation_status = visible` count. Hidden and
pending-moderation responses do not block expiry or refunds. A saved visible
response still counts if its creation acknowledgement is unfinished. A response
still in a prepared transaction holds a lock on the parent; the scanner skips
that request until a later pass. New responses and acceptance remain forbidden
after the deadline, even before the scanner runs. Administrators can resolve
conflicts through the [award or refund actions](conflict-resolution.md). The
scanner does not automatically choose or pay a contributor.

The scanner also revisits requests already marked `expired` by the older
status-only implementation. Those with visible responses become `conflicted`;
those without visible responses receive their existing held reward back.
Existing `conflicted` requests are reconsidered too: if their last visible
response becomes hidden or pending, expiry and refund can proceed on the next
scan. Conflicts that still have visible responses are skipped without using up
the scan batch, so they cannot block other overdue requests. It never creates a
refund without a matching held escrow or refunds completed, released, or
already-refunded holds.
Reputation stays unchanged during refunds and conflict classification.

## Schedule

Set a positive interval in `backend/.env`, then recreate Campus:

```dotenv
REQUEST_EXPIRY_SCAN_INTERVAL_SECONDS=60
```

The default is 60 seconds. Each pass examines up to 100 eligible requests, with
unlocked requests considered first in deadline order. The next interval begins
after that pass finishes, so scans within one worker never overlap. Scans can
run in several Campus workers safely. Requests that expire while Campus is
stopped are picked up after startup.

## Transactions and recovery

For requests with visible responses, Campus changes the status to `conflicted` in one
ordinary local transaction. Points is not contacted and the escrow stays held.

For requests without visible responses:

1. Campus locks a due request with `FOR UPDATE SKIP LOCKED` and persists an
   `expire_request` coordinator operation with server-derived owner and request
   IDs. It releases the intake lock before preparing native transactions.
2. The Campus participant locks the parent and rechecks the deadline, status,
   owner, acceptance fields, and absence of **visible** responses. It prepares
   the status change to `expired`.
3. Points locks the escrow and requester wallet. It verifies the escrow belongs
   to the requester and is still `held`, credits the escrow amount, marks it
   `refunded` with a settlement time, and inserts a `refund` ledger entry. Those
   changes are prepared together; reputation is not changed.
4. The existing coordinator records its immutable COMMIT only after both Yes
   votes. Otherwise it records ABORT. It replays that decision until both
   participants acknowledge, and exposes completion only after both do.

The coordinator uses authenticated HTTP and each service accesses only its own
database. A partial unique index allows one active or committed expiry per
request; another allows one refund ledger entry per escrow. Locks and native
prepared journals prevent duplicate credits across retries and lost messages.
A crash after intake or preparation is handled by the existing five-second
recovery workers. Prepared voters wait for the coordinator's decision; they do
not independently abort after a timeout.

If a refund attempt is fully aborted, a later expiry pass can create a new
attempt after the cause is fixed. An unfinished operation is left to recovery;
a committed one is never refunded again. A missing or mismatched escrow causes
an abort rather than an invented credit. Already-expired legacy rows retain
that status if their refund cannot complete, and failures are logged.

## API and database inspection

Request reads and `GET /requests?status=conflicted` expose the new status.
`GET /operations/{operation_id}` remains owner-only and supports automatic
expiry operations:

```json
{
  "operation": "expire_request",
  "operation_id": "fca0388e-bb03-4d20-bf90-d68679f44993",
  "status": "processing",
  "created_at": "2026-10-22T17:00:00Z",
  "refund_points": 5,
  "request": null,
  "error_code": null
}
```

`refund_points` is the intended amount while processing. Only `completed`
confirms the refund; then `request` contains the expired request. A fully
aborted operation has `status: aborted` and an `error_code`. As with the existing
2PC flows, individual database reads can observe a participant's committed
change while the other participant still awaits decision delivery.

```sql
SELECT id, title, status, expires_at, accepted_response_id
FROM requests
ORDER BY id DESC;

SELECT id, request_id, state, decision, error_code
FROM distributed_transactions
WHERE operation = 'expire_request'
ORDER BY created_at DESC;
```

## Migrations and validation

Both APIs apply migrations on startup with the development Compose setup.
Start Points before Campus so the first refund scan can reach Points:

```sh
docker compose up -d --wait points-api
docker compose up -d --wait campus-api
```

Campus adds the `conflicted` enum value and the expiry operation uniqueness
index. Points adds the unique refund-per-escrow index. Downgrading Campus drops
its index but keeps the additive PostgreSQL enum label.

The implementation lives in `app/managers/expiration.py`,
`app/managers/expiration_participant.py`, and `app/points/managers/refund.py`.
Workflow tests use two disposable PostgreSQL databases as described in
[request creation](requests.md) and verify classification, balances, rollback,
concurrent scans, prepared locks, lost acknowledgements, and crash recovery.
