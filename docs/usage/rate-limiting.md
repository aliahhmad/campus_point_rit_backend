# Authentication rate limits

Campus provides optional rate limiting for authentication routes. It is disabled
by default:

```env
RATE_LIMIT_ENABLED=true
```

Recreate Campus to apply the setting. The configured limits are defined in
`app/rate_limit/config.py`:

| Action | Limit |
| --- | --- |
| Registration | 3 per hour |
| Login | 5 per 15 minutes |
| Forgot password | 3 per hour |
| Email verification | 10 per minute |
| Token refresh | 20 per minute |
| Password-reset form | 10 per minute |
| Password-reset submission | 5 per hour |

A rejected request returns HTTP 429 with the rate-limit handler's retry
information. These decorators do not automatically limit request creation,
response submission, acceptance, refunds, or internal transaction endpoints.

With Redis enabled, the limiter uses the configured Redis connection; otherwise
its store is in memory. In-memory limits are local to an application process.
Redis is optional and must be supplied separately from the default Compose stack.

Do not disable transaction recovery because authentication traffic was rate
limited. Internal participant communication uses its own service credential and
must remain available for prepared operations to finish.
