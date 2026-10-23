# Upgrade and compatibility notes

CampusPoint extends an authentication-oriented FastAPI foundation with a
separate Points service, native prepared transactions, responses, acceptance,
reputation, expiry refunds, and administrator conflict resolution.

## Updating an existing checkout

1. Preserve the existing `.env` and database volumes.
2. Add missing Points credentials, the shared service token, and expiry settings
   from `.env.example`. Do not replace working secrets with example values.
3. Ensure both PostgreSQL instances have prepared transactions enabled.
4. Rebuild/start Points and Campus so each applies its own migrations.
5. Confirm both services are healthy before testing financial actions.

```sh
docker compose up --build -d --wait points-api
docker compose up --build -d --wait campus-api
```

Campus and Points use separate Alembic histories. Database connection settings
inside Compose differ from host tools: host ports are 5433 and 5434; container
connections use port 5432.

## Existing data

- Locations require a CSV import after creating a fresh Campus database.
- Wallet initialization is idempotent for the same user ID; reads do not create
  missing wallets or issue grants.
- Changing the blocklist does not re-moderate existing content.
- The expiry worker revisits eligible legacy expired rows and conflicts that
  no longer have visible responses. It refunds only a matching held escrow.
- A recorded distributed decision is immutable. Preserve coordinator records,
  participant journals, and native preparations when upgrading.
- Administrator preparation messages extend the original payload types, keeping
  original owner-acceptance and automatic-refund hashes compatible with recovery.

Read [2PC](development/two-phase-commit.md), [recovery](development/recovery.md),
and [migrations and tests](development/testing.md) before changing transaction
schemas or performing maintenance on unfinished operations.
