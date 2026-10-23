# Live Swagger documentation

Start the services, then open:

- [Campus Swagger](http://localhost:8001/docs)
- [Points Swagger](http://localhost:8003/docs)

Campus Swagger includes `API_ROOT` in its address when a prefix is configured.
Each application exposes its generated schema at `/openapi.json`; the schema
URL itself follows FastAPI's default and does not use Campus's router prefix.

Use an access token or account credentials through Swagger's authorization
controls for public protected endpoints. Internal participant and wallet actions
require `X-Service-Token` and are intended for service communication. Use demo
data before trying write operations interactively.

This static documentation site does not embed a frozen OpenAPI JSON file.
The running service is the source of exact current schemas and response models.
ReDoc is disabled for Campus. See [the API catalog](api.md) for endpoint groups.
