# CampusPoint limitations and follow-up work

The main request/reward workflows are implemented. The following boundaries
remain relevant when extending or hosting the project:

- Registration and wallet initialization use separate commits. A global crash
  between those commits is outside the request coordinator's recovery path.
- Moderation uses literal configured words. No public manual moderation action,
  retroactive rescan, or abuse-obfuscation detection is implemented.
- No public request/response editing or deletion API is implemented.
- Prepared transactions retain locks until the saved decision can be delivered;
  availability depends on coordinator/database recovery.
- The existing CI Python job runs the original `tests/` suite rather than the
  dedicated cross-service PostgreSQL workflows.
- React provides conflict acceptance; an administrator refund API exists without
  a frontend refund button.
- Application/package fallback metadata still contains inherited defaults;
  deployment environment settings and MkDocs identity are separate.

Potential improvements need their own requirements and review. Do not interpret
this list as scheduled work or authorization to implement unrelated changes.
