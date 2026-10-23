# HTML and email templates

Templates are stored under `app/templates/`:

| File | Use |
| --- | --- |
| `index.html` | Optional backend landing page |
| `email/base.html` | Shared CampusPoint email layout and fallback action link |
| `email/welcome.html` | Account verification email |
| `email/password_reset.html` | Password reset email |
| `password_reset_form.html` | Backend reset form when no frontend redirect is configured |
| `password_reset_success.html` | Backend reset confirmation |

Set `API_TITLE=CampusPoint` for the application name and
`MAIL_FROM_NAME="CampusPoint RIT"` for the sender label. `FRONTEND_URL` points
verification and reset actions at the React website; otherwise the email flow
uses backend URLs derived from `BASE_URL`.

Email contexts supply `application`, `name`, `base_url`, and `expiry_minutes`.
Welcome emails use `verification`; reset emails use `reset_token`. Verification
expires after 10 minutes and password-reset tokens after 30 minutes.

Keep action URLs, expiry information, and copyable fallback links intact when
changing the HTML. Recreate the backend after environment changes and send test
emails through a configured development SMTP service before relying on them in
a demo. Static screenshots of the original template are not CampusPoint UI.
