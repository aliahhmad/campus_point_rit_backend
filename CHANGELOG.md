# CampusPoint changelog

## Unreleased — CampusPoint implementation

This entry summarizes the implemented project features; it does not declare a
numbered release or date.

### Services and data

- Separate Campus and Points APIs and PostgreSQL databases.
- Active campus location selection with bundled CSV import.
- Idempotent wallet initialization with one 100-point opening grant.
- Request, response, coordinator, participant, escrow, and points-ledger models
  with separate Campus/Points migrations.

### Request workflows

- Request creation reserves five points in escrow for a one-hour request.
- Blocklist moderation returns visible, hidden, or pending on check failure.
- Confirmed request browsing with location, search, status, and ownership filters.
- One response per other contributor/request, with moderated visibility.
- Owner acceptance completes a live request, transfers the held five points,
  and adds one contributor reputation point.
- Expiry scanning refunds requests with no visible responses and marks answered
  requests conflicted. Hidden and pending responses do not block refunds.
- Administrator conflict resolution reuses acceptance and refund settlement.

### Coordination and recovery

- Native PostgreSQL prepare/commit/rollback protocol with durable immutable
  decisions, participant votes/acknowledgements, payload-bound GIDs, and journals.
- Idempotent operation intake and caller-owned polling.
- Campus coordinator and Points participant recovery on startup and between
  periodic passes; independent configurable expiry worker.
- Isolated tests and real PostgreSQL workflows for accounting, concurrency,
  rollback, message loss, and crash recovery.

### Documentation

- CampusPoint setup, API catalog, 2PC, recovery, testing, and demo-hosting guides.
- Replaced upstream template branding and stale single-service instructions.

## Upstream provenance

The inherited release history is preserved separately in
[the upstream archive](docs/history/template-changelog.md). Those release
numbers and links belong to FastAPI Template, not CampusPoint.
