# Backend API keys

API-key support remains in Campus even though the React frontend no longer
includes key-management pages or links. Keys identify a user and are sent as:

```http
X-API-Key: <your-key>
```

For example, call `GET http://localhost:8001/wallet/me` with that header.
Include `API_ROOT` in the URL if configured. Use one authentication method per
request; the dependency checks JWT authentication before falling back to keys.

## Management endpoints

| Method | Path | Permission |
| --- | --- | --- |
| GET / POST | `/users/keys` | Own keys; list or create |
| GET / PATCH / DELETE | `/users/keys/{key_id}` | Own key; inspect, rename/toggle, or delete |
| GET | `/users/keys/by-user/{user_id}` | Administrator list of another user's keys |
| PATCH / DELETE | `/users/keys/by-user/{user_id}/{key_id}` | Administrator update or deletion |

Only creation returns the raw key. Store it securely; later reads return metadata
rather than the secret. Keys are stored hashed, can be deactivated or deleted,
and currently have no expiration time. An administrator cannot create a key for
another account through these endpoints.

Keys retain the authenticated user's role and account restrictions. The stored
`scopes` list does not currently implement a separate fine-grained authorization
policy. See Swagger for validated creation/update shapes and key IDs.

Internal Points APIs use `X-Service-Token`, not public user API keys. Never place
that internal credential in a browser build.
