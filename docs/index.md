# CampusPoint backend

CampusPoint lets users post campus requests, contribute answers, and reward a
selected response. The backend runs a Campus API and a Points API with separate
PostgreSQL databases. Campus coordinates native PostgreSQL two-phase commit
when a request action also changes escrow or wallet balances.

## Start here

- [Quick start](quick-start.md): configure and start the development stack.
- [Configuration](usage/configuration/environment.md): database, service URLs,
  secrets, moderation, expiry, and frontend integration.
- [API reference](reference/api.md): public and internal endpoint groups.
- [Two-phase commit](development/two-phase-commit.md) and
  [recovery workers](development/recovery.md): decisions, retries, and outages.
- [Testing](development/testing.md): isolated service tests and real PostgreSQL
  workflows.

## Services

| Component | Owns | Local address |
| --- | --- | --- |
| Campus API | Users, locations, requests, responses, moderation, coordinator | `http://localhost:8001` |
| Points API | Wallets, reputation, escrow, financial ledger | `http://localhost:8003` |
| Campus PostgreSQL | Campus business records and coordinator state | `localhost:5433` |
| Points PostgreSQL | Points records and participant journal | `localhost:5434` |

The frontend calls Campus. Services communicate through authenticated internal
HTTP; neither service reads the other's database directly.

## Request lifecycle

A new account receives one 100-point opening grant. Creating a request holds
five available points for one hour. Other users can answer while the request is
open and unexpired. Accepting a visible response completes the request and
awards its contributor the held five points and one reputation point.

An overdue, unaccepted request with no visible responses expires and refunds its
requester. With visible responses it becomes `conflicted`, retaining its escrow.
An administrator can select a visible response or refund the requester.
Hidden and pending responses do not prevent automatic refunds.

A configured word check determines content visibility. Operation completion,
request lifecycle status, and moderation status are separate concepts.

The backend's authentication and optional administration infrastructure derive
from [FastAPI Template](https://github.com/seapagan/fastapi-template). Upstream
license notices are retained; these guides describe CampusPoint's implementation.
