# Hosting CampusPoint for demos

The backend needs two persistent PostgreSQL databases with native prepared
transactions enabled, two long-running API processes, and working internal
HTTP connectivity. The recovery and expiry workers run inside those processes.

## One-server deployment

For a small demo, the four existing services can run on one virtual server in
separate containers and databases. Provision persistent storage, generated
secrets, and a reverse proxy providing HTTPS to Campus. The current Compose file
is a development configuration: it uses source mounts, `--reload`, and loopback
bindings. Review those settings before using it as a public deployment.

Keep Points and database ports private. Configure service-network URLs so Points
can read Campus decisions and Campus can reach Points. Preserve coordinator
records, participant journals, database data, and prepared state across restarts.
Use both Alembic histories for updates; do not rebuild databases from scratch.

PostgreSQL hosting must allow nonzero `max_prepared_transactions`. Verify this
before selecting a managed database. A sleeping or short-lived function runtime
cannot continuously run these recovery and expiry loops as currently implemented.

## Frontend on Vercel, backend on your computer

A public HTTPS tunnel to Campus can support a temporary demo while Points and
both databases remain local. Keep the computer awake and connected, Docker
running, and the tunnel active. A `localhost` URL in a deployed browser does not
point to your computer for other visitors.

Set the frontend build environment:

```env
VITE_API_BASE_URL=https://your-public-campus-api.example.com
```

Include the Campus API prefix if configured. In the backend environment set:

```env
FRONTEND_URL=https://your-site.vercel.app
CORS_ORIGINS=https://your-site.vercel.app
```

Recreate the API container after changing environment values. Rebuild/redeploy
the frontend after changing its API URL. A temporary tunnel's hostname can change;
update that URL when needed. Frontend routing must fall back to `index.html` on
refresh. Vite's development proxy is not part of the production build.

The frontend README contains its Vercel build and SPA-rewrite instructions.
A backend restart does not authorize dropping prepared transactions or changing
a recorded decision. Read [recovery](../development/recovery.md) before demoing
network failures or restarts.

## Demo checks

1. Both API health checks pass and both schemas are migrated.
2. Locations are imported and demo accounts have initialized wallets.
3. Frontend login and profile wallet reads work through HTTPS.
4. Creating a request holds five points; selecting a response awards five points
   and one reputation point.
5. A no-visible-response expiry refunds; visible responses create a conflict.
6. An administrator can resolve a conflict through the documented APIs.
7. Polling reports coordinator completion before claiming an award/refund.

Use [workflow tests](../development/testing.md) with disposable databases for
repeatable failure injection. Do not use real account balances as test fixtures.
