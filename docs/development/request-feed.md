# Request creation and browsing

The authenticated frontend provides **Campus requests** at `/requests` and a
**New request** form at `/requests/new`.

Each request card links to `/requests/{request_id}`. The detail page displays
the description, location, requester, reward, dates, and moderation state,
alongside paginated responses. Eligible contributors can submit an answer;
request owners cannot answer their own requests. Request information and
responses refresh every five seconds. The answer form preserves unresolved
submissions in session storage and polls the shared operations endpoint.

- `GET /locations` lists active predefined locations for the dropdown.
- `GET /requests` lists confirmed requests, newest first, with location labels.
  It accepts `search` (literal title substring), `location_id`, `status`, `mine`,
  `page` (default 1), and `size` (default 20, maximum 100). The response contains
  `items`, `page`, `size`, and `has_more`.
- `GET /requests/{request_id}` returns one request with the same fields and
  visibility checks as the feed. Missing, inaccessible, and unconfirmed requests
  return 404, including when opening a direct link.
- A request appears only after the coordinator records a finished COMMIT.
  Visible requests can be browsed by other users. Pending and hidden requests
  remain accessible to their owner.

New requests are checked by `app/managers/moderation.py:auto_moderate_request`
before insertion in the Campus participant transaction. Both the title and
description are checked against `MODERATION_BLOCKED_WORDS`, a comma-separated
setting with a starter list of common abusive words. Matching ignores case and
uses literal whole words, so punctuation around a word still matches, but a
substring inside a longer word does not. Requests without matches are saved as
`visible`; matches are saved as `hidden`. Only a failed moderation check returns
`pending`: the error is logged and request creation continues with content
accessible only to its owner. The check runs locally; database and Points service
errors retain their existing transaction behavior. This is a basic word check
and does not detect every form of abuse or deliberate spelling obfuscation.

Override the list in `backend/.env` and restart Campus, for example:

```dotenv
MODERATION_BLOCKED_WORDS=fuck,shit,bitch,asshole
```

An empty list approves all new content. Existing requests keep their saved
moderation status. No manual approval/rejection actions are implemented yet.

The list refreshes every five seconds. Search, filters, and pagination are
stored in the page URL.

The creation form submits to the existing `POST /requests` endpoint. It saves
the submission's generated `Idempotency-Key` and exact payload in session
storage before sending. An uncertain failure retries the same submission;
once an operation ID is known it checks `GET /operations/{id}` instead.
Processing operations are checked every five seconds. Users can reopen the
creation page in the same browser tab after navigation or reload to resume.
While unresolved, submitted fields and repeat creation are disabled.

Confirmed success reports the five-point hold and links to **My requests**.
Insufficient points and invalid locations show an error and allow a corrected
new submission. Service failures preserve the original submission for retry.
