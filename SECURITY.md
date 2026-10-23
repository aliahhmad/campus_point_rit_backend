# CampusPoint security reporting

This repository is a development/demo project. No supported-release schedule,
response-time guarantee, or production security certification is declared here.
Review the current implementation and deployment before using real data.

## Report a vulnerability

Contact this project's maintainers through a private channel associated with
the CampusPoint repository. If private vulnerability reporting is available on
the repository, use it. A dedicated security email has not been configured in
these docs; do not send project reports to the upstream template author.

Do not publish credentials, raw tokens, personal data, exploitable details, or
application database dumps in public issues. Include affected code/behavior,
reproduction steps using disposable data, impact, and any proposed mitigation.

## Relevant boundaries

Keep service tokens, JWT secrets, and database credentials outside frontend
builds and Git. Internal APIs require the shared service token. Role checks,
request visibility, and escrow state must be enforced on the server.

Prepared transactions require coordinated resolution. Do not manually undo a
preparation solely because it is old; first establish its durable decision.
Use disposable databases for failure injection and destructive workflow tests.

`SECURITY-REVIEW.md` contains inherited historical review notes, not a current
CampusPoint audit or assurance that every item applies to this checkout.
