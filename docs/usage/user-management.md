# User management and authentication

Campus provides registration, email verification, login, access-token refresh,
password recovery, profile editing, and administrator account controls.
Paths below include `API_ROOT` when configured.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/register/` | Register and initialize a one-time funded wallet |
| POST | `/login/` | Exchange email/password for access and refresh tokens |
| POST | `/refresh/` | Obtain a new access token using the refresh token |
| GET | `/verify/` | Verify an account using its emailed token |
| POST | `/forgot-password/` | Request a password-reset email |
| GET / POST | `/reset-password/` | Reset form/redirect and reset submission |
| GET | `/users/me` | Read authenticated profile name and email |
| GET | `/users/` | Administrator user list or one user through `user_id` |
| GET | `/users/search` | Administrator account search |
| PUT | `/users/{user_id}` | Edit an authorized user's profile |
| POST | `/users/{user_id}/password` | Change an authorized user's password |
| POST | `/users/{user_id}/make-admin` | Grant administrator role |
| POST | `/users/{user_id}/ban` | Ban an account |
| POST | `/users/{user_id}/unban` | Unban an account |
| DELETE | `/users/{user_id}` | Administrator deletion, subject to constraints |

Use the running [Swagger UI](../reference/swagger.md) for exact payloads,
parameters, and response models. `/users/` returns a paginated object when no
`user_id` is supplied, and one account when it is supplied.

JWT authentication uses `Authorization: Bearer <access-token>`. Refresh tokens
are separate from access tokens and must be sent to `/refresh/`; unverified or
banned users cannot use protected APIs. Access tokens default to 120 minutes;
refresh tokens last 30 days. Verification tokens last 10 minutes and password
reset tokens 30 minutes.

The backend also supports [API-key authentication](api-keys.md). React stores
its session and unresolved submission keys in browser session storage and uses
JWT access/refresh tokens. Admin navigation derives from the server-side role;
the backend authorizes each actual action.

Profile edit payloads include a password field; it is a replacement value, not a
current-password verification challenge. Use the separate password endpoint for
an explicit password change. No public resend-verification route is currently
registered. Local demos can use [CLI verification](add-user.md).
