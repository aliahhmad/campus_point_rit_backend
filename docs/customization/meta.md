# CampusPoint metadata

Metadata controls display information in Swagger, HTML/email contexts, CLI
output, and the documentation site. These sources are separate:

| Source | Controls |
| --- | --- |
| `backend/.env` | Campus settings such as `API_TITLE`, `API_DESCRIPTION`, `REPOSITORY`, `FRONTEND_URL`, and sender name |
| `app/config/metadata.py` | Fallback title, description, repository, contact, license, and year |
| `pyproject.toml` | Package name, version, description, and CLI project details |
| `mkdocs.yml` | Documentation site title, navigation, and repository link |

## Set the application display values

```env
API_TITLE=CampusPoint
API_DESCRIPTION=Campus requests, responses, escrowed rewards, and distributed settlement.
REPOSITORY=https://github.com/aliahhmad/rit_csci_652_dist_project
MAIL_FROM_NAME=CampusPoint RIT
FRONTEND_URL=http://localhost:5173
```

Use the deployed frontend address for hosted demos. Recreate the API containers
after environment changes. Points has its own `CampusPoint Points API` title;
these Campus settings do not rename the Points application.

## Fallback metadata

The checked-in fallback module and package metadata still contain values
inherited from the original FastAPI foundation. Environment overrides control
the configured Campus title; the fallback values are not the project's
maintainer contact details.

When updating the fallback module, keep the `MetadataBase` fields expected by
`app/config/helpers.py`. Use CampusPoint's title/description and this project's
repository. Supply an actual maintainer contact only when one is established;
do not reuse the upstream author's contact as CampusPoint support information.
Preserve the upstream MIT copyright and license notices in `LICENSE.txt`.

The optional interactive tool is:

```sh
docker compose exec campus-api api-admin custom metadata
```

This tool rewrites both `app/config/metadata.py` and package metadata in
`pyproject.toml`. Review its output and changes before committing them. Updating
application display metadata does not configure a deployment address, change
service ownership, or alter the 2PC protocol.

See [email templates](templates.md) for the template variables and
[environment configuration](../usage/configuration/environment.md) for URLs.
