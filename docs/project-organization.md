# Project organization

| Path | Responsibility |
| --- | --- |
| `app/main.py` | Campus FastAPI application and lifespan workers |
| `app/resources/` | Public Campus APIs and authenticated internal transaction routes |
| `app/managers/coordinator.py` | Durable operation orchestration and recovery |
| `app/managers/*_participant.py` | Campus preparation and guarded business changes |
| `app/managers/expiration.py` | Overdue classification and refund intake |
| `app/managers/conflict_resolution.py` | Administrator resolution validation |
| `app/managers/moderation.py` | Configured word checks |
| `app/models/` | Campus ORM models |
| `app/schemas/` | Validated public request and response shapes |
| `app/database/` | Campus connections and bundled location data |
| `app/transactions/` | Native prepare/finish protocol, GIDs, message schemas, worker lifecycle |
| `app/points/main.py` | Independent Points FastAPI application and recovery worker |
| `app/points/managers/` | Wallet initialization, holds, awards, refunds, participant recovery |
| `app/points/models/` | Wallet, escrow, ledger, and participant journal models |
| `app/migrations/` | Campus Alembic history |
| `app/points/migrations/` | Points Alembic history |
| `app/config/` | Environment settings, display metadata, logging, OpenAPI customization |
| `app/commands/` | `api-admin` account and maintenance tools |
| `app/templates/` | Email, root-page, and password-reset HTML |
| `tests_requests/`, `tests_points/` | Isolated request and Points tests |
| `tests_workflow/` | Cross-service workflows using disposable PostgreSQL databases |
| `tests/` | Original account/infrastructure tests with a separate test database |
| `docker-compose.yml` | Four-service development stack and persistent volumes |
| `docs/`, `mkdocs.yml` | This documentation website and navigation |

Ordinary SQLAlchemy sessions handle intake, reads, and local operations.
Native prepared transactions use dedicated `asyncpg` connections. Keep those
paths separate: ordinary session cleanup must not finish a native preparation.
