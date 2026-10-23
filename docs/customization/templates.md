# Customize the Templates

There are several HTML templates used at this time, all are stored in the
`templates/` folder or a subfolder of this.

- `app/templates/index.html` - This template is shown when the root of
the API is visited using a web browser instead of an API call. Use it to display
vasic details about your API and usage instructions, point to the documentation
etc. The default output is below for an example:

![Default Index
Page](https://github.com/seapagan/fastapi-template/raw/main/static/images/html_index.png)

- `app/templates/email/base.html` - shared CampusPoint email layout, with inline
  styles, a hidden inbox preview, an action button, and a copyable fallback link.
- `app/templates/email/welcome.html` - verifies a new user's email address.
- `app/templates/email/password_reset.html` - sends a password reset link.

Set `API_TITLE=CampusPoint` to control the application name in email subjects and
content, and `MAIL_FROM_NAME="CampusPoint RIT"` for the sender's display name.
Set `FRONTEND_URL` to the frontend's public URL (`http://localhost:5173` locally)
so email links open the React verification and password reset pages. If unset,
links use `BASE_URL` for the backend flow. Restart the backend after changing
these settings.

The email contexts supply `expiry_minutes` from the same constants that set token
expiration: 10 minutes for verification and 30 minutes for password reset. Both
templates also receive `application`, `name`, and `base_url`; the welcome email
uses `verification`, and the password reset email uses `reset_token`.
