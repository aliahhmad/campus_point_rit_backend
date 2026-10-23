# Metrics and logs

Campus exposes optional Prometheus metrics. Points currently has its own
readiness route and recovery logging, not the same metrics registration.

```env
METRICS_ENABLED=true
API_TITLE=CampusPoint
```

Recreate Campus, then inspect <http://localhost:8001/metrics>. The metrics route
is registered at `/metrics`; it is not added through the prefixed public router.
When metrics are disabled the route is absent.

HTTP metrics include request counts, latency, in-progress requests, and payload
sizes. Custom counters cover authentication failures, key validation, login
attempts, and rate-limit violations. The namespace derives from the configured
API title, so `API_TITLE=CampusPoint` produces `campuspoint` prefixes. Inspect the
actual scrape output for metric and label names.

Metrics do not replace durable inspection of `distributed_transactions`,
`transaction_participants`, `participant_transactions`, and `pg_prepared_xacts`.
There are no dedicated escrow/recovery backlog dashboards configured by default.

## Logs

```sh
docker compose logs --tail=100 -f campus-api points-api
```

Campus logging options include `LOG_LEVEL`, `LOG_CATEGORIES`, `LOG_PATH`,
`LOG_FILENAME`, `LOG_ROTATION`, `LOG_RETENTION`, `LOG_COMPRESSION`, and
`LOG_CONSOLE_ENABLED`. Uvicorn/lifespan recovery messages also appear in service
output. Do not share secrets, raw authentication headers, or personal data in
public troubleshooting reports.
