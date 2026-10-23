# Optional response caching

Campus includes opt-in caching around selected user and API-key reads.
Request feeds, wallet reads, operation polling, and financial settlement do not
use these response-cache decorators.

```env
CACHE_ENABLED=true
REDIS_ENABLED=false
CACHE_DEFAULT_TTL=300
```

Recreate Campus after changing settings. With Redis disabled, caching is local
to the process. When configured, startup initializes Redis and falls back to
in-memory caching if the cache connection fails.

```env
REDIS_ENABLED=true
REDIS_HOST=your-redis-host
REDIS_PORT=6379
REDIS_DB=0
```

Configure `REDIS_PASSWORD` for a secured Redis deployment. Redis is not one of
the four default Compose services; provision it separately before enabling it.

`app/cache/decorators.py` turns `@cached` into a no-op when caching is disabled.
Some decorators specify a five-minute TTL directly; `CACHE_DEFAULT_TTL` supplies
the value only when the decorator does not set one. Key builders include user
identity and pagination where required. Account and API-key write handlers
invalidate related cache namespaces.

Do not infer wallet settlement or coordinator decisions from cached profile
responses. Those are durable database state handled by the transaction protocol.
Inspect Campus logs for cache initialization and invalidation errors.
