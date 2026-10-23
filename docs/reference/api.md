# CampusPoint API reference

Campus defaults to `http://localhost:8001`; prefix its paths with `API_ROOT` when
configured. Points defaults to `http://localhost:8003` and exposes internal
wallet/transaction APIs. Exact payloads and generated schemas are available in
[the running Swagger UIs](swagger.md).

## Authentication and accounts

| Method | Campus path | Purpose |
| --- | --- | --- |
| POST | `/register/` | Register and initialize a wallet |
| POST | `/login/` | Access/refresh tokens |
| POST | `/refresh/` | Refresh access token |
| GET | `/verify/` | Verify email token |
| POST | `/forgot-password/` | Request reset email |
| GET / POST | `/reset-password/` | Reset form/redirect and submission |
| GET | `/users/me` | Authenticated profile |
| GET | `/users/` | Administrator paginated users or single `user_id` lookup |
| GET | `/users/search` | Administrator user search |
| PUT | `/users/{user_id}` | Authorized profile update |
| POST | `/users/{user_id}/password` | Authorized password update |
| POST | `/users/{user_id}/make-admin` | Administrator promotion |
| POST | `/users/{user_id}/ban` | Administrator ban |
| POST | `/users/{user_id}/unban` | Administrator unban |
| DELETE | `/users/{user_id}` | Administrator deletion subject to constraints |

Protected actions accept `Authorization: Bearer <access-token>` or a valid
`X-API-Key`. The user must satisfy account and role checks. See
[user management](../usage/user-management.md) and [API keys](../usage/api-keys.md).

## Campus requests and points

| Method | Campus path | Contract |
| --- | --- | --- |
| GET | `/locations` | Active location dropdown |
| GET | `/wallet/me` | Authenticated wallet balance and reputation |
| GET | `/requests` | [Feed filters, pagination, visibility](../development/request-feed.md) |
| GET | `/requests/{request_id}` | Confirmed accessible request |
| POST | `/requests` | [Request creation and five-point hold](../development/requests.md) |
| GET | `/requests/{request_id}/responses` | [Permitted answers, pagination, `mine`](../development/responses.md) |
| POST | `/requests/{request_id}/responses` | [Response submission](../development/responses.md) |
| GET | `/responses/{response_id}` | Permitted single answer |
| POST | `/requests/{request_id}/responses/{response_id}/accept` | [Owner acceptance](../development/acceptance.md) or [admin resolution](../development/conflict-resolution.md) |
| POST | `/requests/{request_id}/refund` | [Administrator refund](../development/conflict-resolution.md) |
| GET | `/operations/{operation_id}` | Caller-owned operation status and recovery trigger |

Each public POST request action requires `Idempotency-Key`. Creation returns
201 after completion; acceptance/refund returns 200. An unfinished operation
returns 202 with `status: processing`. Poll its operation ID or retry the exact
original action/key after uncertain failures. Confirmed aborts stay aborted.

There is no public request edit/delete API or manual moderation endpoint.
Conflicted request lists reuse `GET /requests?status=conflicted`; visibility
rules continue to apply. See [expiry](../development/expiration.md).

## Backend API keys

| Method | Campus path |
| --- | --- |
| GET / POST | `/users/keys` |
| GET / PATCH / DELETE | `/users/keys/{key_id}` |
| GET | `/users/keys/by-user/{user_id}` |
| PATCH / DELETE | `/users/keys/by-user/{user_id}/{key_id}` |

Owner and administrator authorization is required as described in the
[key guide](../usage/api-keys.md). The frontend has no key-management pages.

## Internal service APIs

All internal paths require `X-Service-Token`. They are not browser APIs.

| Service | Method | Path | Purpose |
| --- | --- | --- | --- |
| Points | GET | `/internal/wallets/{user_id}` | Read existing wallet |
| Points | PUT | `/internal/wallets/{user_id}/initialize` | Idempotent wallet/opening-grant initialization |
| Campus | GET | `/internal/transactions/{transaction_id}/decision` | Durable coordinator decision |
| Campus / Points | POST | `/internal/transactions/{transaction_id}/prepare` | Request/hold preparation |
| Campus / Points | POST | `/internal/transactions/{transaction_id}/prepare-acceptance` | Acceptance/reward preparation |
| Campus | POST | `/internal/transactions/{transaction_id}/prepare-expiry` | Expiry/refund preparation on Campus |
| Points | POST | `/internal/transactions/{transaction_id}/prepare-refund` | Refund preparation on Points |
| Campus / Points | POST | `/internal/transactions/{transaction_id}/commit` | Apply verified COMMIT |
| Campus / Points | POST | `/internal/transactions/{transaction_id}/abort` | Apply verified ABORT |

Response creation uses Campus's local participant path through the coordinator;
it does not contact Points or expose a separate response-prepare HTTP endpoint.
See [2PC](../development/two-phase-commit.md) and [recovery](../development/recovery.md).

## Health and errors

- Campus `GET /heartbeat` reports its heartbeat.
- Points `GET /heartbeat` reports liveness; `GET /ready` checks database readiness.
- Campus `GET /metrics` exists only when metrics are enabled; it is not prefixed
  through `API_ROOT`.
- Business errors use `detail.code` and `detail.message`; durable operation
  failures may include `detail.operation_id`.
- Input validation uses FastAPI's `detail` array. Authentication and existing
  user-management errors may use string details.
- Rate limiting is implemented for selected authentication endpoints and is
  opt-in. See [limits](../usage/rate-limiting.md).

Request, response, and operation visibility checks can return 404 for records
the caller cannot access. An HTTP error or timeout is not sufficient proof that
a distributed operation performed no writes.
