# Resolve conflicted requests as an administrator

Administrators have two choices for a confirmed, overdue `conflicted` request:
select a visible response and release the reward, or refund the requester.
Both use the existing Campus/Points native PostgreSQL two-phase commit protocol.
Ordinary users retain the existing owner-only acceptance rules before expiry.

## Frontend calls

Use the current list and detail endpoints to browse requests:

```http
GET /requests?status=conflicted
GET /requests/12
GET /requests/12/responses
```

These reads keep their existing visibility and pagination rules. There is no
separate administrator list API.

| Administrator's choice | Endpoint | Completed result |
| --- | --- | --- |
| Choose response 7 | `POST /requests/12/responses/7/accept` | Request `completed`; selected contributor receives 5 points and +1 reputation |
| Refund requester | `POST /requests/12/refund` | Request `expired`; requester receives their 5 held points; reputation unchanged |

The award endpoint is the existing acceptance endpoint. The refund endpoint is
new and requires an administrator account. Both require authentication and an
`Idempotency-Key` header. Neither needs a request body. IDs, recipients, points,
and the administrator's identity are derived by the server.

```js
// Choose exactly one action. Keep this key for retries of that action.
const key = crypto.randomUUID();
const path = action === "award"
  ? `/requests/${requestId}/responses/${responseId}/accept`
  : `/requests/${requestId}/refund`;

const response = await fetch(`/api${path}`, {
  method: "POST",
  headers: {
    Authorization: `Bearer ${accessToken}`,
    "Idempotency-Key": key,
  },
});
const result = await response.json();
```

`/api` is the Vite proxy prefix; direct backend calls use the configured
`API_ROOT` instead. Generate a new key for each deliberate action and preserve
it until its outcome is known. Never switch actions while reusing a key.

HTTP **200** with `status: completed` confirms settlement. Award responses use
the existing [acceptance response](acceptance.md), including `recipient_id`,
`accepted_response`, and the completed `request`. Refund responses use the
existing [expiry response](expiration.md):

```json
{
  "operation": "expire_request",
  "operation_id": "fca0388e-bb03-4d20-bf90-d68679f44993",
  "status": "completed",
  "created_at": "2026-10-22T18:30:00Z",
  "refund_points": 5,
  "request": {
    "id": 12,
    "requester_id": 2,
    "location_id": 1,
    "title": "Library seats",
    "description": "Are any tables available?",
    "reward_points": 5,
    "status": "expired",
    "moderation_status": "visible",
    "created_at": "2026-10-22T16:00:00Z",
    "expires_at": "2026-10-22T17:00:00Z",
    "accepted_response_id": null,
    "accepted_at": null
  },
  "error_code": null
}
```

HTTP **202** means `status: processing`; `request` is null. Poll the existing
`GET /operations/{operation_id}` using the same administrator account every
five seconds until `completed` or `aborted`. Do not display payment success
while processing. If a network failure leaves the outcome uncertain, retry
with the same key. Fully aborted attempts remain aborted; after fixing the
cause, a new attempt requires a new key.

## Eligibility and errors

The request must be confirmed, overdue, `conflicted`, and unaccepted. Admins
can resolve a conflict even if its parent request is hidden or pending. A
selected response must belong to the request, be confirmed and `visible`, and
be written by someone other than the requester. Hidden or pending responses
cannot win. A refund is allowed despite visible responses: it is an explicit
administrator decision. Existing completed settlements cannot be reversed.

| HTTP status | Error | Meaning |
| --- | --- | --- |
| 401 | Existing authentication error | Missing or invalid credentials |
| 403 | `admin_required` | User is not a current, verified, unbanned administrator |
| 403 | `request_owner_required` | Ordinary owner acceptance rules apply outside conflicted requests |
| 403 | `self_response_forbidden` | Requester cannot receive their own reward |
| 404 | `request_not_found` | Request is missing or creation is unconfirmed |
| 404 | `response_not_found` | Answer is missing, unpublished, unconfirmed, or belongs elsewhere |
| 409 | `request_not_conflicted` | Request cannot be resolved as a conflict |
| 409 | `request_not_expired` | Deadline has not passed |
| 409 | `request_already_accepted` | Another response has already won |
| 409 | `request_not_open` | Request was settled before preparation |
| 409 | `resolution_in_progress` | Another refund operation already exists for this request |
| 409 | `idempotency_conflict` | Key identifies a different action, request, response, or caller |
| 409 | `escrow_not_found`, `escrow_mismatch`, `escrow_already_settled` | Existing escrow cannot be settled |
| 422 | FastAPI validation array | Invalid ID or missing/invalid idempotency key |
| 503 | `recipient_wallet_missing`, `requester_wallet_missing`, `service_unavailable` | A participant or wallet is unavailable |

Business errors return `detail.code` and `detail.message`. Aborted operations
also include `detail.operation_id`; polling returns `status: aborted` and
`error_code`. Ordinary owner acceptance may also report its existing errors.

## Accounting, authorization, and recovery

The durable operation records the initiating administrator as its owner for
audit and polling. Its trusted payload separately records the actual requester
and selected contributor. The administrator does not receive the requester
refund or another contributor's reward.

Campus checks the administrator's current database role and account state
again during preparation. It locks and rechecks the request and, for awards,
the selected response. The normal Points reward and refund participants lock
the held escrow and relevant wallet and write the existing ledger entries.
The coordinator commits only after both Yes votes, persists its immutable
decision, and retries delivery until both services acknowledge. Prepared voters
wait for that decision; timeouts do not authorize unilateral aborts.

Concurrent awards, refunds, retries, and automatic scans share the existing
request and escrow locks and ledger uniqueness constraints. Only one settlement
can complete. New administrator preparation message variants preserve the
original message formats and payload hashes for in-flight owner acceptances
and automatic refunds. No database migration is needed.

Tests in `tests_workflow/test_admin_resolution.py` run against disposable Campus
and Points databases, covering permissions, deadlines, moderation, accounting,
retries, competing decisions, rollback, lost acknowledgements, and crash recovery.
