# CampusPoint backend

CampusPoint is a campus request-and-response application with a five-point
reward system. Its backend consists of two FastAPI services, each owning a
PostgreSQL database. The Campus service coordinates native PostgreSQL two-phase
commit (2PC) whenever a request action must also settle points.

This backend includes authentication and account administration, location
selection, automatic content moderation, request and response APIs, escrowed
rewards, acceptance and reputation awards, expiry refunds, administrator conflict
resolution, and background transaction recovery.

## Contents

- [Architecture](#architecture)
- [Run locally](#run-locally)
- [Configuration](#configuration)
- [Accounts and administration](#accounts-and-administration)
- [Requests, moderation, and accounting](#requests-moderation-and-accounting)
- [Public API](#public-api)
- [Two-phase commit](#two-phase-commit)
- [Recovery loops and expiry scanning](#recovery-loops-and-expiry-scanning)
- [Database inspection](#database-inspection)
- [Migrations and checks](#migrations-and-checks)
- [Troubleshooting](#troubleshooting)
- [Code and detailed documentation](#code-and-detailed-documentation)

## Architecture

| Service | Responsibility | Local address |
| --- | --- | --- |
| `campus-api` | Users, authentication, locations, requests, responses, moderation, 2PC coordinator | `http://localhost:8001` |
| `points-api` | Wallets, reputation, escrow, points ledger, Points participant and recovery | `http://localhost:8003` |
| `campus-db` | Campus records and durable coordinator state | `localhost:5433` |
| `points-db` | Wallets, escrow, ledger, and Points participant journal | `localhost:5434` |

The frontend calls Campus. Campus calls Points over HTTP using the shared
`X-Service-Token` credential. Points calls Campus to obtain recorded transaction
decisions. Neither service connects directly to the other service's database;
IDs shared across the boundary do not have cross-database foreign keys.

The Compose configuration runs PostgreSQL 18.1 and enables
`max_prepared_transactions=100` on both databases. Database volumes survive normal
container stops and recreation. Published service and database ports are bound
to loopback for local development.

## Run locally

### Requirements

- Docker with Docker Compose. Docker Desktop or Colima can provide the runtime.
- For Python tools outside containers: Python 3.10–3.14 and `uv`.
- A configured `backend/.env`. Commands below run from this backend directory.

### 1. Configure the environment

On first setup:

```sh
cp .env.example .env
```

Keep an existing configured `.env` when updating the project. Replace the
placeholder Campus database credentials, Points database password, JWT secret,
and shared service token. Generate a separate random value for each secret:

```sh
openssl rand -hex 32
```

Also add or update these local settings:

```env
I_READ_THE_DAMN_DOCS=true
DB_ADDRESS=localhost
DB_PORT=5433
POINTS_DB_ADDRESS=localhost
POINTS_DB_PORT=5434
BASE_URL=http://localhost:8001
FRONTEND_URL=http://localhost:5173
CORS_ORIGINS=http://localhost:5173
```

`I_READ_THE_DAMN_DOCS=true` is required by the existing Campus startup guard.
The host database ports above are for tools running outside Docker. Compose
supplies container database addresses and port 5432 to the APIs automatically.
Use a separate `TEST_DB_NAME` for the Campus test database.

### 2. Initialize the databases and locations

Start your Docker runtime first. With Colima, run `colima start`.

```sh
docker compose up -d --wait campus-db points-db
docker compose run --build --rm --no-deps campus-api alembic upgrade head
```

Before creating requests, import the bundled
[app/database/rit_locations.csv](app/database/rit_locations.csv). Follow
[Load campus locations](docs/development/locations.md) for the import commands.
Migrations create the location table; they do not import the CSV. Repeated
imports skip existing building codes.

### 3. Start the APIs

Start Points before Campus so the initial recovery and expiry passes can reach
both services:

```sh
docker compose up --build -d --wait points-api
docker compose up --build -d --wait campus-api
docker compose ps
```

Each API applies its own Alembic migrations before starting. For later starts,
the same commands reuse the existing database volumes and imported locations.

| Endpoint | Purpose |
| --- | --- |
| `http://localhost:8001/docs` | Campus Swagger UI |
| `http://localhost:8003/docs` | Points Swagger UI; internal actions require the service token |
| `http://localhost:8001/heartbeat` | Campus heartbeat |
| `http://localhost:8003/ready` | Points database readiness |

Campus URLs include `API_ROOT` when configured; Points URLs do not use that
prefix.

### Restart, update, and stop

For code updates, rerun the build/start commands above. After changing `.env`,
recreate the services to load the new environment:

```sh
docker compose up -d --force-recreate --wait points-api
docker compose up -d --force-recreate --wait campus-api
```

Inspect service logs or stop the stack:

```sh
docker compose logs --tail=100 -f campus-api points-api
docker compose down
```

`docker compose down` retains database volumes. Adding `-v` deletes the stored
users, requests, wallets, and transaction history.

## Configuration

The full template is [.env.example](.env.example). The main application settings
are:

| Setting | Purpose |
| --- | --- |
| `DB_USER`, `DB_PASSWORD`, `DB_NAME` | Campus database credentials and name |
| `DB_ADDRESS`, `DB_PORT` | Campus database connection outside Compose; host port is 5433 |
| `POINTS_DB_USER`, `POINTS_DB_PASSWORD`, `POINTS_DB_NAME` | Separate Points database credentials and name |
| `POINTS_DB_ADDRESS`, `POINTS_DB_PORT` | Points database connection outside Compose; host port is 5434 |
| `TEST_DB_NAME` | Disposable database used by the original Campus test suite |
| `SECRET_KEY` | JWT signing secret; use a generated value of at least 32 characters |
| `POINTS_SERVICE_TOKEN` | Same nonempty internal HTTP credential in both APIs |
| `POINTS_API_URL` | Campus-to-Points address; local default `http://localhost:8003` |
| `POINTS_CAMPUS_API_URL` | Points-to-Campus address, including Campus `API_ROOT` if configured |
| `API_ROOT` | Optional Campus URL prefix, such as `/v1`; default is empty |
| `BASE_URL` | Public Campus address used when constructing backend links |
| `FRONTEND_URL` | Website address for verification and password-reset links |
| `CORS_ORIGINS` | Comma-separated allowed browser origins |
| `MODERATION_BLOCKED_WORDS` | Comma-separated words checked in new requests and responses |
| `REQUEST_EXPIRY_SCAN_INTERVAL_SECONDS` | Positive delay between expiry passes; default 60 seconds |
| `MAIL_*` | SMTP configuration for account emails |

Compose sets the internal service URLs and database addresses. If you run the
APIs directly, configure those values yourself. Hostnames such as `campus-db`
and `points-api` are Docker network addresses, not host-machine addresses.

For a hosted frontend, set its public origin in `CORS_ORIGINS` and its address
in `FRONTEND_URL`. The frontend's `VITE_API_BASE_URL` must point to the public
Campus API, including any API prefix. Keep `POINTS_SERVICE_TOKEN`, database
credentials, and `SECRET_KEY` out of frontend settings and Git.

Optional template facilities include the SQLAdmin interface, logging, caching,
metrics, and authentication rate limits. Their switches and defaults are listed
in `.env.example`; Redis is optional.

## Accounts and administration

Authentication supports JWT access/refresh tokens and backend API keys.
Unverified or banned users cannot use protected APIs. Registration initializes
a Points wallet with a one-time **100-point opening grant**. Repeating wallet
initialization preserves the existing balance and does not issue another grant.

Registration waits for Points initialization; a reported initialization failure
returns 503 and rolls back the new Campus user. This path uses separate local
commits, not the request 2PC coordinator. It therefore does not have the same
cross-service crash recovery guarantee as request creation and settlement.

For demo accounts, the CLI can create a user, verify them without email, and
assign an administrator role:

```sh
docker compose exec campus-api api-admin user create
docker compose exec campus-api api-admin user list
```

Use the actual ID from the list in these examples:

```sh
docker compose exec campus-api api-admin user verify 1
docker compose exec campus-api api-admin user admin 1
```

Creation prompts for account details and requires Points to be running. Verify
and promotion are separate actions. Backend API-key endpoints remain available;
the current frontend does not provide API-key management pages.

## Requests, moderation, and accounting

### Creating and answering requests

- A request contains an active location, a title, and a description. Titles are
  limited to 200 characters; descriptions and response answers to 5,000.
- Campus derives ownership, contributor identity, timestamps, and the fixed
  five-point reward. Clients cannot choose a payout amount or recipient.
- Creating a request removes five available points and records them in a held
  escrow. The request expires one hour after creation.
- Requests have no public edit or delete API.
- Only other contributors can answer a confirmed, visible, open, unexpired
  request. `UNIQUE(request_id, contributor_id)` permits one response per user,
  including hidden or pending responses. Posting an answer does not spend points.

### Moderation and visibility

New request titles/descriptions and response answers use the same configured
blocklist. Matching is case-insensitive and checks literal whole words:

| Check result | `moderation_status` |
| --- | --- |
| No configured word matches | `visible` |
| A configured word matches | `hidden` |
| The moderation check fails | `pending` |

An empty blocklist approves all new content. Updating it does not retroactively
recheck existing rows. This is a local word check, not an external AI service.

Only confirmed creations appear in reads. Published requests are available to
other authenticated users; hidden/pending requests are owner-only. A response's
hidden/pending content is contributor-only, subject to access to its parent.
Request owners cannot read another contributor's unpublished answers.

Request `status`, content `moderation_status`, and operation `status` describe
different things and should not be treated as interchangeable.

### Acceptance, expiry, and conflicts

| Situation | Request outcome | Points and reputation |
| --- | --- | --- |
| Owner accepts a visible response before expiry on a visible `open` or `under_review` request | `completed` with acceptance ID/time | Release held five points to the selected contributor and add one reputation point |
| Unaccepted request is overdue and has no visible responses | `expired` through refund 2PC | Return held five points to the requester; reputation unchanged |
| Unaccepted request is overdue and has visible responses | `conflicted` | Keep escrow held |
| Administrator selects a confirmed visible response on an overdue conflict | `completed` | Same five-point reward and +1 reputation |
| Administrator refunds an overdue conflict, even with visible responses | `expired` | Return held five points to the requester; reputation unchanged |

Normal owners cannot accept after expiry. Administrators resolve conflicts
through the existing acceptance endpoint or the admin-only refund endpoint.
The selected answer must belong to that request and cannot be the requester's
own answer. Selection is final; competing awards and refunds cannot both settle
the same held escrow.

Hidden and pending responses **do not count** when deciding automatic refunds.
A visible saved response counts even if its creation acknowledgement is still
unfinished. If a conflicted request later has no visible responses, the scanner
can expire and refund it. Completed requests are excluded from automatic expiry.

`under_review` is supported by the model and owner acceptance rules. New requests
start `open`; the expiry worker does not automatically assign `under_review`.

Points writes use the existing `opening_grant`, `hold`, `reward`, and `refund`
ledger types. For example, with two wallets starting at 100 each:

| Stage | Requester available | Contributor available | Held escrow | Contributor reputation gained |
| --- | --- | --- | --- | --- |
| Before request | 100 | 100 | 0 | 0 |
| After creation | 95 | 100 | 5 | 0 |
| After acceptance | 95 | 105 | 0 | 1 |
| After refund instead of acceptance | 100 | 100 | 0 | 0 |

Acceptance transfers the existing hold; it does not charge the requester again.
Retries do not add another credit or reputation increment.

## Public API

Paths below are relative to Campus, including `API_ROOT` if configured. Use
`Authorization: Bearer <access-token>` for authenticated requests. Swagger at
`/docs` provides the complete authentication, profile, user-administration, and
API-key contracts.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/locations` | List active locations |
| GET | `/wallet/me` | Read the authenticated user's available points and reputation |
| GET | `/requests` | List permitted requests with pagination, search, location, status, and `mine` filters |
| GET | `/requests/{request_id}` | Read a permitted request |
| POST | `/requests` | Create a request and hold five points |
| GET | `/requests/{request_id}/responses` | List permitted responses; supports pagination and `mine` |
| POST | `/requests/{request_id}/responses` | Submit one answer |
| GET | `/responses/{response_id}` | Read a permitted response |
| POST | `/requests/{request_id}/responses/{response_id}/accept` | Owner acceptance or administrator conflict resolution |
| POST | `/requests/{request_id}/refund` | Administrator refund of a conflict |
| GET | `/operations/{operation_id}` | Read and resume the caller's durable operation |

There is no separate admin conflict-list endpoint. Administrators reuse
`GET /requests?status=conflicted` with normal visibility rules.

### Create a request

```http
POST /requests
Authorization: Bearer <access-token>
Idempotency-Key: <new-UUID-for-this-submission>
Content-Type: application/json

{
  "location_id": 1,
  "title": "Library study space",
  "description": "Are any quiet tables available?"
}
```

Submit a response with `{"answer": "There are tables on the second floor."}`.
Acceptance and refund actions need no body. They use IDs in the URL and
server-derived identities and amounts.

### Idempotency and asynchronous outcomes

All four public POST actions above require `Idempotency-Key`. Keys are 1–128
characters, start with an ASCII letter or digit, and otherwise allow letters,
digits, `.`, `_`, `:`, and `-`.

Use a new key for each deliberate action. Preserve the same key and content
when retrying an uncertain request. Changing the caller, action, request,
response, or submitted content while reusing a key returns 409.

| Response | Meaning |
| --- | --- |
| 201 for creation; 200 for acceptance/refund, with `status: completed` | Every participant acknowledged the recorded COMMIT |
| 202 with `status: processing` | Coordination or decision delivery remains unfinished; do not report payment success |
| 4xx/5xx business error | Inspect `detail.code`, `detail.message`, and any `detail.operation_id` |

Poll `GET /operations/{operation_id}` until `status` is `completed` or `aborted`.
Polling returns HTTP 200 for a valid operation; the body determines its outcome.
An operation is visible only to its recorded owner; other callers receive 404.
For administrator resolutions, that owner is the initiating administrator, while
the payload separately records the actual financial recipient.

A confirmed aborted operation stays aborted. Correct its cause and use a new
key for a fresh attempt. A timeout or 503 is not proof that nothing happened;
use any returned operation ID or retry the original key to establish the result.

## Two-phase commit

### Which actions participate?

| Operation | Campus preparation | Points preparation |
| --- | --- | --- |
| `create_request` | Insert moderated request | Debit available balance, create held escrow and hold ledger entry |
| `create_response` | Insert moderated response | None; uses the coordinator with Campus as its only participant |
| `accept_response` | Complete request and record selected response/time | Release escrow, credit contributor, add +1 reputation and reward ledger entry |
| `expire_request` | Mark request expired | Refund requester, settle escrow, insert refund ledger entry |

Administrator awards reuse `accept_response`; administrator refunds reuse
`expire_request`. Classifying a request as `conflicted` uses a normal Campus
transaction because it makes no Points changes. Registration wallet
initialization is the separate idempotent local-commit flow described above.

### Prepare, decide, and deliver

1. **Persist intake.** Campus commits the operation's UUID, caller, idempotency
   key, and trusted payload to `distributed_transactions`. Before preparation,
   the coordinator reserves any new entity IDs durably and registers the
   required participants.
2. **Prepare local work.** Each participant validates its inputs and eligibility
   under locks, performs its business writes, inserts a local journal row, and
   executes PostgreSQL `PREPARE TRANSACTION` on a dedicated connection. It votes
   Yes only after preparation is durable. Ordinary ORM sessions do not finish
   these native transactions.
3. **Record one decision.** Campus records COMMIT only after all required Yes
   votes. A failed prepare or unconfirmed prepare reply causes ABORT. The
   decision is persisted before delivery and cannot be replaced later.
4. **Deliver the decision.** Campus sends the saved decision to participants,
   delivering to Points before completing its own participant. Participants
   verify Campus's recorded decision before applying `COMMIT PREPARED` or
   `ROLLBACK PREPARED`.
5. **Finish acknowledgement.** Campus records each acknowledgement and marks
   the coordinator operation `finished` only after all participants acknowledge.
   The API exposes the completed business result at that point.

```mermaid
sequenceDiagram
    participant C as Campus coordinator
    participant CD as Campus PostgreSQL
    participant P as Points API
    participant PD as Points PostgreSQL
    C->>CD: Persist operation and identifiers
    C->>CD: Business writes + PREPARE TRANSACTION
    C->>P: Authenticated prepare request
    P->>PD: Business writes + PREPARE TRANSACTION
    PD-->>P: Durable preparation
    P-->>C: Yes vote
    C->>CD: Record immutable COMMIT or ABORT
    C->>P: Deliver saved decision
    P->>PD: COMMIT PREPARED or ROLLBACK PREPARED
    P-->>C: Acknowledge
    C->>CD: Finish Campus participant
    C->>CD: Save acknowledgements and finished state
```

This diagram shows a two-participant action. Response creation uses the same
coordinator without a Points participant.

### Durable state and duplicate protection

| Record | Location | Purpose |
| --- | --- | --- |
| `distributed_transactions` | Campus database | Operation payload, caller, key, entity IDs, immutable decision, progress and error |
| `transaction_participants` | Campus database | Required services, Yes/No votes, acknowledgements |
| `participant_transactions` | Each service's database | Local native transaction ID and prepared/committed/aborted journal state |
| `pg_prepared_xacts` | PostgreSQL system view | Native preparations that survived disconnection or process restart |
| `escrows`, `points_transactions` | Points database | Held/released/refunded rewards and financial ledger |

Coordinator progress follows:

```text
preparing -> commit_decided -> finished  (decision: commit)
preparing -> abort_decided  -> finished  (decision: abort)
```

Public results translate these records into `processing`, `completed`, or
`aborted`. The `finished` coordinator state alone does not imply success; inspect
its decision.

Native transaction IDs have the form
`campuspoint:<service>:<transaction-UUID-hex>:<payload-hash>`. The hash binds retries
to the same validated message even before its journal row becomes visible.
Advisory locks serialize coordination and participant messages per operation.
Request, response, wallet, and escrow row locks protect eligibility and accounting
across different operation IDs.

Unique constraints enforce one response per contributor/request, one escrow per
request, and one opening grant per user. Partial unique indexes prevent multiple
reward or refund entries per escrow and duplicate active/committed expiry jobs.
Escrow status checks prevent a released or refunded hold from being settled again.
Abort journal records also reject delayed prepare messages after an abort.

### Visibility and availability

Prepared business writes are not visible to normal readers, but retain database
locks. List/detail reads additionally require a finished committed creation
operation before publishing a new request or response.

Decision delivery can commit one participant before the other. Independent
reads may temporarily observe that service's committed state while the operation
is still processing. Clients must wait for coordinator completion before claiming
that an award or refund finished.

A recorded COMMIT must eventually finish as COMMIT, even after a deadline passes
or an acknowledgement is lost. During an outage, a prepared participant can
remain blocked until the coordinator and communication recover. A timeout never
authorizes an independent participant to reverse the decision.

## Recovery loops and expiry scanning

Workers start with each FastAPI application's lifespan, run an initial pass,
and continue while that process is alive. Shutdown cancels and awaits them.
They are application background tasks, not external cron jobs.

| Worker | Service | Delay after each pass | Work |
| --- | --- | --- | --- |
| Coordinator recovery | Campus | 5 seconds | Resume up to 100 oldest unfinished operations from durable state |
| Participant recovery | Points | 5 seconds | Find native preparations and unfinished journal entries; obtain and apply Campus decisions |
| Request expiry scan | Campus | `REQUEST_EXPIRY_SCAN_INTERVAL_SECONDS`, default 60 | Inspect up to 100 eligible overdue requests; classify conflicts or enqueue refund operations |

The delay begins after a pass completes, so a long pass extends the effective
interval. Expiry and coordinator recovery are separate workers. Request posting
and normal owner acceptance enforce their deadlines even before a scan runs.

### How transaction recovery proceeds

- **Campus crashed after intake or preparation:** reconstruct the original
  payload and reserved IDs, repeat preparation idempotently, and finish the
  decision protocol.
- **A prepare succeeded but its reply was lost:** the coordinator can record
  ABORT; delivery rolls back any preparation that actually succeeded.
- **A decision exists but delivery or acknowledgement failed:** replay that same
  decision until each participant acknowledges. No new payout is created.
- **Points cannot reach Campus, or Campus has no decision yet:** keep waiting.
  Points does not infer ABORT from a timeout, an unavailable coordinator, or a
  missing decision.
- **A process crashed after `COMMIT PREPARED` but before updating its journal:**
  the now-visible journal row proves its business transaction committed.
  Recovery marks that journal committed without repeating the business writes.

Authenticated `GET /operations/{operation_id}` also advances unfinished
coordination; browser polling is an additional recovery trigger. Recovery
therefore continues without the original browser request, and prepared state
survives API restarts through PostgreSQL.

### How expiry scanning proceeds

The database clock determines whether a request is overdue. Campus selects due,
unaccepted requests with `FOR UPDATE SKIP LOCKED`, so another worker or a
prepared action can hold a request without blocking the entire scan.

With visible responses, Campus records `conflicted` in a local transaction and
keeps the escrow held. Without visible responses, it saves an `expire_request`
operation, releases intake locks, and runs normal refund 2PC. The Campus
participant rechecks expiry and visible-response absence under lock; Points
rechecks escrow ownership and its held status.

Existing conflicts are reconsidered if their visible responses disappear.
Legacy `expired` rows without a completed refund are also eligible for repair.
Conflicts that still have visible responses do not consume the scan batch.
Already accepted requests and active/committed expiry operations are excluded.
After a fully aborted automatic refund, a later scan may create a fresh attempt;
unfinished operations remain the recovery worker's responsibility.

## Database inspection

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

## Migrations and checks

### Schema migrations

Compose runs migrations automatically on API startup. To apply them explicitly
to running services:

```sh
docker compose exec campus-api alembic upgrade head
docker compose exec points-api alembic -c alembic-points.ini upgrade head
```

Campus and Points have separate migration histories. When managing PostgreSQL
outside Compose, enable prepared transactions on both databases before starting
2PC work; a zero `max_prepared_transactions` prevents preparation and changing
that setting requires a database restart.

### Validation and service tests

For local Python tooling, install the locked dependencies, including development
tools:

```sh
uv sync --locked
uv run python -m pytest tests_requests tests_points -o addopts='' -q
```

These suites cover validation, moderation, authorization boundaries, schemas,
and isolated service behavior. By default, request intake tests use temporary
SQLite and Points tests mock their database. They do not prove native 2PC.

### Real PostgreSQL workflow tests

Create **two disposable PostgreSQL databases**, with prepared transactions
enabled, and supply their URLs explicitly. For example, assuming a dedicated
test server on port 5543 with the following databases already created:

```sh
REQUESTS_TEST_DATABASE_URL='postgresql+asyncpg://test_user:test_password@127.0.0.1:5543/campus_test' \
POINTS_TEST_DATABASE_URL='postgresql+asyncpg://test_user:test_password@127.0.0.1:5543/points_test' \
uv run python -m pytest tests_workflow -o addopts='' -q
```

**Workflow fixtures truncate application tables and roll back test preparations.
Never point these variables at development/demo data or production databases.**
The URLs must identify different databases. Without both variables, workflow
fixtures skip their database-dependent tests.

Workflow coverage includes creation, response visibility, wallet conservation,
reward/reputation and refund accounting, permissions, competing settlements,
idempotent retries, local rollback, lost prepare/commit acknowledgements, and
crash recovery. These tests exercise native prepared transactions through both
services' ASGI routes.

The original `tests/` suite uses `TEST_DB_NAME` and drops/recreates its schema.
Configure that database separately before running it; do not use the application
database for this suite either.

Useful code and documentation checks:

```sh
uv run python -m ruff check app tests_requests tests_points tests_workflow
uv run python -m ruff format --check app tests_requests tests_points tests_workflow
uv run python -m pymarkdown scan README.md
```

## Troubleshooting

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

## Code and detailed documentation

| Path | Responsibility |
| --- | --- |
| `app/resources/` | Campus HTTP endpoints and authentication dependencies |
| `app/managers/coordinator.py` | Durable coordination, decisions, acknowledgements, and Campus recovery |
| `app/managers/*_participant.py` | Campus native preparations and guarded request/response changes |
| `app/managers/expiration.py` | Due-request classification and refund intake |
| `app/managers/conflict_resolution.py` | Administrator validation and refund operations |
| `app/managers/moderation.py` | Configurable blocked-word checks |
| `app/transactions/` | Native PostgreSQL prepare/finish, GIDs, journals, schemas, and worker lifecycle |
| `app/points/` | Points API, financial participants, wallet initialization, and participant recovery |
| `app/migrations/`, `app/points/migrations/` | Separate Alembic migrations |
| `tests_requests/`, `tests_points/`, `tests_workflow/` | Validation/service tests and real database workflows |

Detailed contracts and setup notes:

- [Location import](docs/development/locations.md)
- [Wallet initialization and profile reads](docs/development/wallets.md)
- [Request creation and escrow](docs/development/requests.md)
- [Response API](docs/development/responses.md)
- [Acceptance, rewards, and reputation](docs/development/acceptance.md)
- [Automatic expiry, refunds, and conflicts](docs/development/expiration.md)
- [Administrator conflict resolution](docs/development/conflict-resolution.md)

The authentication, account tooling, and optional administration infrastructure
originate from [seapagan/fastapi-template](https://github.com/seapagan/fastapi-template).
See [LICENSE.txt](LICENSE.txt) for licensing.
