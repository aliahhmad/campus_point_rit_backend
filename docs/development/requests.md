# Request creation and the five-point hold

Campus and Points coordinate creation using PostgreSQL two-phase commit.
Each service accesses only its own database. Campus contacts Points through
internal HTTP authenticated with the shared `POINTS_SERVICE_TOKEN`.

## Start the services

From `backend/`, run:

```sh
docker compose up --build -d --wait
```

Compose enables `max_prepared_transactions=100` on both databases and each API
applies its own migrations before starting. Existing database volumes are
retained. A locally managed PostgreSQL instance also needs a nonzero
`max_prepared_transactions` and a restart before using this flow.

Both APIs must have the same nonempty `POINTS_SERVICE_TOKEN`. Campus uses
`POINTS_API_URL` to reach Points. Points uses `POINTS_CAMPUS_API_URL` to look up
Campus decisions; include the Campus `API_ROOT` in that URL if configured.
Compose sets these addresses for the service network.

Campus also [expires overdue requests](expiration.md) on startup and every
60 seconds by default. Configure `REQUEST_EXPIRY_SCAN_INTERVAL_SECONDS` to change
the interval. Requests without visible responses expire and refund their held reward through
2PC; requests with visible responses become `conflicted` and keep the reward
held. Hidden and pending responses do not prevent a refund.

## Public API

Use the existing JWT or API-key authentication. Include `API_ROOT` in Campus
URLs if configured.

```http
POST /requests
Authorization: Bearer <access-token>
Idempotency-Key: submission-123
Content-Type: application/json

{
  "location_id": 1,
  "title": "Library crowding",
  "description": "Are there any empty study tables?"
}
```

Titles allow 1–200 characters; descriptions allow 1–5,000. Outer whitespace is
trimmed. Blank text, extra fields, and missing/inactive locations are rejected.
Campus derives the owner from authentication and fixes the reward at five.
Use a new key for a new submission; keep the same key and content when retrying.
Keys allow 1–128 ASCII letters, digits, dots, underscores, colons, and hyphens,
starting with a letter or digit.

| Result | HTTP status | Response |
| --- | --- | --- |
| Both participants confirmed commit | 201 | `status: completed`, operation ID, and created `request` |
| Decision delivery remains unresolved | 202 | `status: processing`, operation ID, and `request: null` |
| Insufficient available points | 409 | `detail.code: insufficient_points`; both participants abort |
| Key reused by another owner or with different content | 409 | `detail.code: idempotency_conflict` |
| Missing/inactive location | 422 | `detail.code: invalid_location` |
| Service unavailable and abort confirmed | 503 | `detail.code: service_unavailable` |

`GET /operations/{operation_id}` authorizes the owner, retries unfinished work,
and returns `processing`, `completed`, or `aborted`. Other users receive 404.
While abort delivery is unresolved, the operation also remains processing.
Committed decisions are always completed, never changed to abort.

Retries return the same operation and create no additional request, escrow, or
hold entry. A confirmed abort remains aborted for that key; use a new key for
an intentionally new submission after correcting the cause. Malformed input
uses FastAPI's standard 422 errors, and authentication uses the existing 401.

## Flow and code

1. `app/managers/campus_request.py` validates the submission and commits its
   owner, key, and content to `distributed_transactions`.
2. `app/managers/coordinator.py` reserves a request ID, registers both services
   in `transaction_participants`, and asks each to prepare.
3. `app/managers/request_participant.py` validates the location and prepares the
   request insertion in Campus.
4. `app/points/managers/campus_request.py` locks the wallet with `FOR UPDATE`,
   checks for five available points, deducts five, inserts a held escrow, and
   inserts a `hold` ledger entry. These changes share one transaction.
5. `app/transactions/postgres.py` executes `PREPARE TRANSACTION` on dedicated
   connections. Yes means PostgreSQL has stored the preparation durably.
6. Campus records COMMIT only after both Yes votes; otherwise it records ABORT.
   It sends that recorded decision until both participants acknowledge.
7. The public API returns the created request only after both acknowledgements.
   Campus checks the title and description against `MODERATION_BLOCKED_WORDS`
   before insertion. Requests without matches are saved as `visible`; matches
   are saved as `hidden`. Only failures in the moderation check produce `pending`.
   Hidden and pending requests are accessible only to their owner. The feed also
   waits for a finished COMMIT before displaying a request.

The participant GID includes the service, transaction UUID, and a hash of the
validated payload. Repeated messages can verify their identity even while
prepared changes are invisible. Advisory locks serialize messages for one
operation; wallet row locks serialize different submissions spending one wallet.

`participant_transactions` is inserted together with the business changes,
inside the native transaction. While prepared, PostgreSQL's `pg_prepared_xacts`
provides the visible recovery identifier. After COMMIT PREPARED, the journal row
becomes visible and is marked committed. A crash between those actions is
recoverable because journal visibility proves the business commit completed.
Abort records also reject delayed prepare messages.

The Campus and Points lifespans start recovery workers that retry every five
seconds. Campus resumes undecided operations or replays a recorded decision.
Points checks Campus's authenticated decision endpoint and waits when no
decision is available. A timeout alone never permits a Yes voter to abort.
Prepared transactions retain locks until resolved, so keep recovery running.
See the [PostgreSQL PREPARE TRANSACTION documentation](https://www.postgresql.org/docs/current/sql-prepare-transaction.html).

Internal participant endpoints are `POST /internal/transactions/{id}/prepare`,
`POST /internal/transactions/{id}/commit`, and
`POST /internal/transactions/{id}/abort`. Campus also exposes
`GET /internal/transactions/{id}/decision`. All require `X-Service-Token`.

## Verification

```sh
.venv/bin/python -m pytest tests_requests tests_points -o addopts='' -q
```

Those tests isolate validation and local models. For actual prepared-transaction
verification, set `REQUESTS_TEST_DATABASE_URL` and `POINTS_TEST_DATABASE_URL` to
**two disposable PostgreSQL databases**, both with prepared transactions enabled:

```sh
.venv/bin/python -m pytest tests_workflow -o addopts='' -q
```

Workflow tests clear application tables in those test databases. They cover
successful creation, insufficient balance, concurrency, retries, lost prepare
and commit responses, rollback after local writes, owner authorization, and
crash recovery. Optional `WORKFLOW_PG_DATA` and `WORKFLOW_PG_BIN` variables point
to a disposable test server and enable its actual stop/start during the crash
test; leave them unset for an externally managed server.
