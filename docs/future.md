# Current limitations

Implemented workflows include request/response creation, moderation, escrow,
acceptance, reputation, expiry refunds, administrator conflict resolution, and
startup/periodic recovery. These are current project behavior, not future plans.

Known boundaries are tracked in `TODO.md` at the backend root:

- Registration wallet initialization has separate service commits rather than
  the request coordinator's 2PC recovery guarantee.
- Moderation is a configured word check; there is no public manual moderation
  workflow or retroactive rescan.
- Request and response editing/deletion are not public APIs.
- Recovery requires durable databases and a reachable coordinator. Prepared
  transactions can retain locks during outages.
- The current CI test job does not exercise the dedicated CampusPoint workflow
  suite.
- The frontend has administrator acceptance controls, while the backend refund
  action is available as an API.

Treat possible follow-up improvements as design work requiring their own scope;
this page does not promise a release date or a production-readiness assessment.
