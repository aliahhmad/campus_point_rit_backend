# Create and verify accounts

Public registration uses `POST /register/`. The CLI uses the same registration
manager and is convenient for a demo without a frontend:

```sh
docker compose exec campus-api api-admin user create
```

It prompts for email, first/last name, password, and administrator status.
Passwords must be at least eight characters and at most 72 UTF-8 bytes.
Points must be available: creation initializes a wallet and one 100-point grant
before Campus reports registration success. Reinitializing a wallet never grants
another 100 points. See [wallet initialization](../development/wallets.md).

Accounts must be verified before using protected routes. With SMTP configured,
registration sends a verification link to the configured frontend or backend.
For a local demo, list accounts and verify the actual ID:

```sh
docker compose exec campus-api api-admin user list
docker compose exec campus-api api-admin user verify 1
```

Replace `1` with the account's ID. To grant administrator access:

```sh
docker compose exec campus-api api-admin user admin 1
```

Do not insert users directly into Campus PostgreSQL to seed a demo: that bypasses
wallet initialization. CLI creation and public registration initialize both
services through the intended code path.
