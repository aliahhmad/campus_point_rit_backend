# Maintain this documentation

The site uses MkDocs Material. Markdown sources are under `docs/`; site identity,
navigation, and extensions are configured in `mkdocs.yml`. Run from the backend
checkout with its locked development dependencies:

```sh
uv sync --locked
uv run python -m mkdocs serve
```

Open <http://127.0.0.1:9000>. To build a static site without publishing it:

```sh
uv run python -m mkdocs build --strict
uv run python -m pymarkdown scan -r docs
```

The default output is `site/`. This build reads Markdown and does not start API
lifespan workers, alter application databases, deploy the APIs, or publish the
site. Publishing is a separate intentional step.

## API documentation

The live Swagger UIs are <http://localhost:8001/docs> and
<http://localhost:8003/docs>. The [API catalog](../reference/api.md) describes
endpoint groups; exact schemas come from running applications. No static
OpenAPI snapshot is bundled in these guides.

The optional `api-admin docs openapi` command exports a Campus JSON snapshot.
It imports application settings, requires a configured environment, and does not
export Points automatically. A snapshot must be regenerated deliberately after
route changes; MkDocs does not do this on build or serve.

## Editing conventions

- Use CampusPoint's actual ports, service names, and separate database histories.
- Distinguish operation progress, request status, and content moderation.
- Document completed features as implemented and current limitations as limits.
- Preserve 2PC decision/retry invariants in examples; never recommend manual
  rollback just because a preparation is old.
- Keep test database deletion warnings next to destructive test commands.
- Link related pages rather than repeating payloads and setup instructions.
- Keep the rendered copies of root changelog, contribution, security, and conduct
  documents in sync with their root sources, adjusting relative links for `docs/`.
- Preserve upstream attribution and license history without presenting it as
  CampusPoint's release history or support contact information.
