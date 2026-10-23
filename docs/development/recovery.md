# Recovery workers and expiry scanning

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

## How transaction recovery proceeds

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

## How expiry scanning proceeds

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

See [2PC](two-phase-commit.md), [automatic expiry](expiration.md), and
[database inspection and troubleshooting](../troubleshooting.md).
