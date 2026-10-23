# Administration interfaces

CampusPoint has two separate administrator interfaces.

## React administration

The frontend provides **Manage users** and **Conflicted requests**. The latter
uses `GET /requests?status=conflicted` and opens normal request detail pages.
Administrators can accept a visible response on an overdue conflict using the
same acceptance endpoint as request owners. The backend also exposes an
admin-only refund endpoint; its existence does not imply a frontend refund
button is present.

See [conflict resolution](../development/conflict-resolution.md) for permissions,
refund/award contracts, idempotency, and operation polling.

## Optional backend SQLAdmin

```env
ADMIN_PAGES_ENABLED=true
ADMIN_PAGES_ROUTE=/admin
ADMIN_PAGES_TITLE=CampusPoint administration
```

Recreate Campus after changing its environment. With the default route, open
<http://localhost:8001/admin>. This interface is configured separately from
`API_ROOT`. It registers user and API-key views, not a specialized request
settlement screen.

`ADMIN_PAGES_TIMEOUT` controls session lifetime. Configure a stable generated
`ADMIN_PAGES_ENCRYPTION_KEY` when persistent admin sessions are required; the
fallback key is regenerated with a new settings instance. Refer to `.env.example`
for generation instructions.

Use the [CLI](add-user.md) to create/verify an administrator when bootstrapping.
Use the documented acceptance/refund APIs for financial resolution so request
state, escrow, ledger, and reputation go through their guarded 2PC paths.
