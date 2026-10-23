# Account control through the CLI

Run `api-admin` inside the Campus container so its database settings match the
service. Use `--help` for each command's arguments and options:

```sh
docker compose exec campus-api api-admin user --help
```

| Command | Purpose |
| --- | --- |
| `user create` | Interactive registration and wallet initialization |
| `user list` | List accounts and IDs |
| `user show <id>` | Inspect one account |
| `user verify <id>` | Mark an account verified for a local demo |
| `user admin <id>` | Grant administrator role |
| `user admin <id> --remove` | Remove administrator role |
| `user ban <id>` / `user ban <id> --unban` | Ban or unban an account |
| `user search --help` | Inspect account search options |
| `user delete <id>` | Delete an account subject to database constraints |

Replace `<id>` with a real account ID. Request and transaction records use
restrictive foreign keys, so deleting an account with related CampusPoint data
can fail. Account deletion is not a request cancellation or escrow-refund API.

See [account creation](add-user.md), [user HTTP APIs](user-management.md), and
[administrator conflict resolution](../development/conflict-resolution.md).
