# Response API for frontend integration

All endpoints require the existing JWT bearer token or API key. Paths below are
relative to Campus (`http://localhost:8001`), including `API_ROOT` if configured.
Through the Vite proxy, use `/api` as the base URL.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/requests/{request_id}/responses` | Submit an answer |
| GET | `/requests/{request_id}/responses?page=1&size=20` | List permitted answers, oldest first |
| GET | `/responses/{response_id}` | Retrieve one permitted answer |
| GET | `/operations/{operation_id}` | Poll or resume the submitting user's operation |

## Submit an answer

```http
POST /requests/12/responses
Authorization: Bearer <access-token>
Idempotency-Key: <new-UUID-per-submission>
Content-Type: application/json

{
  "answer": "There are free tables on the second floor."
}
```

Send only `answer`, a string of 1–5,000 characters after trimming outer
whitespace. Campus derives `contributor_id` from authentication and assigns the
ID, moderation status, and creation time. Clients cannot set those fields.
Requests accept answers only while confirmed, visible, open, and unexpired.
Users cannot respond to their own requests. Each contributor can submit only
one answer per request, including hidden or pending answers.

A completed creation returns HTTP **201**:

```json
{
  "operation_id": "32ad89e0-a6b1-43e4-af90-85b835e9c29f",
  "status": "completed",
  "created_at": "2026-10-22T16:00:00Z",
  "response": {
    "id": 7,
    "request_id": 12,
    "contributor_id": 5,
    "answer": "There are free tables on the second floor.",
    "moderation_status": "visible",
    "created_at": "2026-10-22T16:00:00Z"
  },
  "error_code": null
}
```

If coordination is unfinished, HTTP **202** returns the same envelope with
`status: "processing"` and `response: null`. Poll `GET /operations/{operation_id}`
every five seconds until `completed` or `aborted`. Polling returns HTTP 200;
inspect `status` and `error_code`. Operations are accessible only to their owner.

Keep the original idempotency key and exact answer when retrying after a timeout
or uncertain failure. Repeating a completed submission returns its original
result, even if the parent request has since closed. Changing the answer, parent,
contributor, or operation type while reusing a key returns an idempotency conflict.
A confirmed aborted operation stays aborted; use a new key for an intentionally
new submission after fixing its cause.

The operation's `status` describes 2PC progress. The answer's
`moderation_status` describes visibility: these are separate fields. No points
are deducted, awarded, or reserved, and no `reward_points` field is returned.

## Moderation and reading answers

The same configured abusive-word check used for request creation checks the
answer. A successful clean check produces `visible`; a blocked word produces
`hidden`; a failed moderation check produces `pending` and logs the error.

Visible answers can be read by users who can access the parent request.
Hidden and pending answers are visible only to their contributor. The requester
cannot see another contributor's hidden or pending answer. Unfinished creation
operations are excluded from both lists and direct lookup.

The list returns:

```json
{
  "items": [],
  "page": 1,
  "size": 20,
  "has_more": false
}
```

Each item has the same shape as `response` in the creation result. The default
page size is 20, with a maximum of 100. Direct lookup returns that object without
the operation envelope. Reading an inaccessible parent or answer returns 404.
Answers remain readable after the parent expires or closes, subject to visibility.

Add `mine=true` to the list URL to retrieve only the current user's response.
The frontend uses `?mine=true&size=1` to check whether the user already answered
without needing to scan every page.

## Error handling

Business errors use `{"detail": {"code": "...", "message": "..."}}`. If a
durably accepted operation aborts, the POST error also includes
`detail.operation_id`. Input validation uses FastAPI's usual `detail` array.

| HTTP status | Code | Meaning |
| --- | --- | --- |
| 401 | Existing authentication response | Missing or invalid credentials |
| 403 | `self_response_forbidden` | Contributor owns the request |
| 404 | `request_not_found` | Parent is absent, unconfirmed, or inaccessible |
| 404 | `response_not_found` | Answer is absent, unconfirmed, or inaccessible |
| 409 | `duplicate_response` | Contributor already answered this request |
| 409 | `idempotency_conflict` | Key belongs to another submission |
| 409 | `request_not_open` | Parent no longer accepts answers |
| 409 | `request_expired` | Parent expiry time has passed |
| 422 | Validation detail array | Invalid answer, ID, pagination, or key |
| 503 | `service_unavailable` | Storage or coordination is unavailable |

## Transaction behavior and setup

The existing coordinator stores `operation: create_response` and reserves a
`response_id`. It registers only Campus in `transaction_participants`.
Campus rechecks the parent under a shared row lock and inserts the moderated
answer and participant journal inside one native PostgreSQL transaction.
`PREPARE TRANSACTION` supplies the Yes vote. The coordinator durably records
COMMIT or ABORT, then delivers it with `COMMIT PREPARED` or `ROLLBACK PREPARED`.
Only a finished COMMIT is exposed to readers. The existing recovery worker
resumes interrupted work. No Points participant or service call is involved.

The database enforces `UNIQUE(request_id, contributor_id)` even for concurrent
submissions with different keys. Concurrent retries with one key share one
operation. Responding does not change the parent request's lifecycle status.

Apply the additive migration and reload Campus from `backend/`:

```sh
docker compose exec campus-api alembic upgrade head
docker compose restart campus-api
```

The `responses` table contains `id`, `request_id`, `contributor_id`, `answer`,
`moderation_status`, and `created_at`. The migration reuses the existing
PostgreSQL moderation enum and adds `distributed_transactions.response_id`.
No Points schema changes are needed.

The new routes and schemas are also available in Campus Swagger at `/docs`.
There is no editing, deletion, or manual moderation endpoint in this change.
