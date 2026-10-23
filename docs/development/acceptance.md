# Accept a response and release its reward

Only the request owner can select a response. Campus and Points coordinate this
action with the same native PostgreSQL two-phase commit used for request
creation. A successful acceptance completes the request and transfers its
existing five-point escrow to the selected contributor, adding one to that
contributor's reputation in the same transaction.

## Frontend API

```http
POST /requests/12/responses/7/accept
Authorization: Bearer <access-token>
Idempotency-Key: <new-UUID-per-selection>
```

No request body is needed. Use the existing JWT or API-key authentication and
include `API_ROOT` if configured. Through the Vite proxy, prefix the path with
`/api`. The server derives the requester and contributor and reads the amount
from the existing escrow; client-supplied payout details cannot alter them.

HTTP **200** reports a completed acceptance:

```json
{
  "operation": "accept_response",
  "operation_id": "fca0388e-bb03-4d20-bf90-d68679f44993",
  "status": "completed",
  "created_at": "2026-10-22T16:30:00Z",
  "reward_points": 5,
  "recipient_id": 5,
  "request": {
    "id": 12,
    "requester_id": 2,
    "location_id": 1,
    "title": "Library seats",
    "description": "Are any tables available?",
    "reward_points": 5,
    "status": "completed",
    "moderation_status": "visible",
    "created_at": "2026-10-22T16:00:00Z",
    "expires_at": "2026-10-22T17:00:00Z",
    "accepted_response_id": 7,
    "accepted_at": "2026-10-22T16:30:00Z"
  },
  "accepted_response": {
    "id": 7,
    "request_id": 12,
    "contributor_id": 5,
    "answer": "There are tables on the second floor.",
    "moderation_status": "visible",
    "created_at": "2026-10-22T16:15:00Z"
  },
  "error_code": null
}
```

If decision delivery is unfinished, HTTP **202** returns `status: "processing"`
and null `request`, `accepted_response`, and `recipient_id`. The `reward_points`
field then describes the intended reward; it does not confirm payment.
Poll `GET /operations/{operation_id}` every five seconds until `completed` or
`aborted`. Polling returns HTTP 200 and is restricted to the operation owner.
Only report successful acceptance/payment when `status` is `completed`.

Reuse the original key when retrying after an uncertain failure. A completed
selection can be replayed after expiry without paying again. Reusing a key for
another request, response, owner, or operation type returns 409. A confirmed
aborted operation remains aborted; after fixing its cause, use a new key for a
new attempt. Another key cannot replace an already accepted response.

Request creation, request lists, and request detail responses now include
`accepted_response_id` and `accepted_at`, both null before acceptance.

## Eligibility and errors

The request must be confirmed, visible, unexpired, and either `open` or
`under_review`, with no previously accepted response. The selected answer must
belong to that request, have a finished committed creation operation, and be
`visible`. Hidden or pending answers cannot be selected. Contributors cannot
receive their own request's reward. The same rules are checked again during
Campus preparation under row locks.

| HTTP status | Error code | Meaning |
| --- | --- | --- |
| 401 | Existing auth response | Missing or invalid credentials |
| 403 | `request_owner_required` | Only the requester may select a response |
| 403 | `self_response_forbidden` | A requester cannot reward their own answer |
| 404 | `request_not_found` | Request is missing, inaccessible, or unconfirmed |
| 404 | `response_not_found` | Answer is missing, unpublished, unconfirmed, or belongs elsewhere |
| 409 | `request_already_accepted` | Another selection already completed |
| 409 | `request_expired` | Acceptance deadline has passed |
| 409 | `request_not_open` | Request is completed or otherwise closed |
| 409 | `request_not_visible` | Request is not published |
| 409 | `idempotency_conflict` | Key belongs to another submission |
| 409 | `escrow_not_found` | No escrow exists for this request |
| 409 | `escrow_mismatch` | Escrow does not belong to the requester |
| 409 | `escrow_already_settled` | Escrow is already released or refunded |
| 422 | FastAPI validation array | Invalid path ID or idempotency key |
| 503 | `recipient_wallet_missing` | Contributor wallet is unavailable |
| 503 | `service_unavailable` | Storage or a participant is unavailable |

Business errors use `detail.code` and `detail.message`. If an accepted operation
aborts, the POST error also includes `detail.operation_id`. Polling an aborted
operation returns its `error_code` with `status: "aborted"`.

## Two-phase commit and accounting

1. Campus stores `operation: accept_response`, the owner, request, response,
   trusted contributor, and idempotency key in `distributed_transactions`.
2. The Campus participant locks the request with `FOR UPDATE` and the selected
   answer with `FOR SHARE`. It rechecks eligibility, sets `status: completed`,
   `accepted_response_id`, and `accepted_at`, and prepares the transaction.
3. Points locks the existing escrow and recipient wallet with `FOR UPDATE`.
   In one transaction it adds the escrow amount to the contributor's available
   points and increments their reputation by one, marks the escrow `released`
   with its recipient, awarded response and settlement time, inserts a `reward`
   ledger entry, and prepares those changes.
4. Campus durably records COMMIT only after both Yes votes. Any No vote records
   ABORT. It then replays that immutable decision until both acknowledge.
5. The API reports completion only after both acknowledgements are durable.

The requester already spent five available points when creating the request.
Acceptance does not debit them again or create another escrow. With two wallets
starting at 100, request creation leaves 95 and 100 available plus a five-point
hold; acceptance leaves 95 and 105 available with no held reward. The selected
contributor gains one reputation point; the requester's reputation stays the
same. Each distinct accepted response adds another reputation point. Retries,
decision replay, and polling do not award additional points or reputation, and
an aborted transaction rolls both increments back. A missing recipient wallet
aborts the selection; it does not issue a new opening grant.

The request row lock prevents competing winners, the escrow row lock prevents
competing settlements, and a partial unique index allows at most one `reward`
ledger entry per escrow even across different operation IDs. Prepared GIDs bind
the payload hash to the transaction, making retries and repeated messages safe.
Each service accesses only its own database and uses authenticated internal HTTP.

Recovery resumes undecided operations or replays a recorded decision after a
crash, including commit/journal gaps. A prepared Yes voter waits for Campus
instead of aborting on a timeout. Expiry rejects new selections and is checked
again during preparation; it cannot reverse an already recorded COMMIT.
During interrupted decision delivery, individual service reads may observe a
committed change while the other participant still awaits delivery. Keep the
operation pending in the UI until the coordinator reports `completed`.

## Migrations and verification

Apply both additive migrations and reload the APIs from `backend/`:

```sh
docker compose exec campus-api alembic upgrade head
docker compose exec points-api alembic -c alembic-points.ini upgrade head
docker compose restart points-api campus-api
```

Campus adds nullable acceptance fields and constraints to `requests`. Points
adds the unique reward-per-escrow ledger index; its existing escrow settlement
columns and reward enum are reused.

```sh
.venv/bin/python -m pytest tests_requests tests_points -o addopts='' -q
```

The acceptance workflow tests run with `tests_workflow` against two disposable
PostgreSQL databases configured as described in [request creation](requests.md).
They check ownership, deadlines, moderation, competing selections, balances,
idempotency, rollback, lost acknowledgements, and crash recovery.
