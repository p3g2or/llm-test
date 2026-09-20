# Field Notes

A small shared notebook with a Python REST API, a TypeScript browser client, and
Azure infrastructure. Notes have a title, body, category, UUID, and UTC creation
time. Users can create, search, filter, read, and delete notes; the board also shows
category totals.

## Architecture

```text
Browser (TypeScript + Vite)
  └─ /api/* → FastAPI routes → NoteService → NoteRepository
                                            ├─ MemoryNoteRepository (local/tests)
                                            └─ AzureNoteRepository → private JSON blobs
```

The frontend uses the same origin as the API. Vite proxies `/api` to the backend
during development. In Azure, the Python app serves both the compiled frontend
and API from one Linux App Service. No CORS configuration is needed.

Terraform's dev environment combines resource-group, storage, and web-app modules.
The web app uses a system-assigned managed identity with **Storage Blob Data
Contributor** access scoped to the note container. Storage account keys and
anonymous blob access are disabled. Terraform supplies the blob endpoint,
container name, storage mode, and board title as App Service settings.
`GET /api/config` passes the title, field limits, and category choices to the UI.

Each note is an immutable JSON blob under `notes/<uuid>.json`; creation never
overwrites an existing blob. Filtering and summary counts scan the small notebook.
Lists are ordered by creation time descending, with UUID as a stable tie-breaker.
Search is case-insensitive and matches title or body. A delete racing with a list
is tolerated. Missing notes return 404; upstream storage failures return a generic
503 without exposing provider details.

This is a shared, unauthenticated notebook intended for small development datasets.
Everyone who can reach the app can read and delete notes. Memory storage is
process-local and resets on restart; use one worker locally. Azure storage persists
across restarts. Blob listings and summary responses are separate reads, not a
transactional snapshot. The health endpoint reports process liveness, not storage
readiness.

## Toolchain and installation

- Python **3.12.13** (`.python-version`)
- Node.js **26.5.0** (`.node-version`)
- uv **0.11.28**
- Terraform **1.9.8** (`.terraform-version`)

Use the version files with your preferred runtime manager. uv can download the
pinned Python interpreter. Dependencies are pinned in `backend/uv.lock`,
`frontend/package-lock.json`, and `infra/environments/dev/.terraform.lock.hcl`.
Initial installation requires internet access; tests run without Azure credentials.

From the repository root:

```sh
uv sync --project backend --locked --python "$(cat .python-version)"
npm ci --prefix frontend
```

## Local development

```sh
bash scripts/dev.sh
```

Open <http://127.0.0.1:5173>. API documentation is at
<http://127.0.0.1:8000/docs>. The script selects in-memory storage; Ctrl-C stops
both development processes. Local environment variables are inherited; `.env`
files are not loaded automatically.

To run each server separately:

```sh
STORAGE_BACKEND=memory uv run --project backend --locked uvicorn fieldnotes.main:app --reload
npm run dev --prefix frontend
```

| Setting | Default | Purpose |
| --- | --- | --- |
| `STORAGE_BACKEND` | `memory` | `memory` or `azure` |
| `BOARD_TITLE` | `Field Notes` | Display title, 1–80 characters |
| `AZURE_STORAGE_ACCOUNT_URL` | empty | Required in Azure mode; Azure Blob HTTPS endpoint |
| `AZURE_STORAGE_CONTAINER` | `notes` | Existing private container |
| `STATIC_DIR` | `fieldnotes/static` beside the Python code | Compiled frontend directory |

Azure mode uses `DefaultAzureCredential`: managed identity in App Service or an
authenticated developer identity locally. Container creation belongs to Terraform,
not application startup. The runtime supports public Azure Blob endpoints.

## API

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/api/health` | Liveness check |
| GET | `/api/config` | Public title, limits, and category choices |
| GET | `/api/notes?category=work&q=release` | List notes with optional filters |
| POST | `/api/notes` | Create a note; returns 201 and a `Location` header |
| GET | `/api/notes/{id}` | Read a note |
| DELETE | `/api/notes/{id}` | Delete a note; returns 204 |
| GET | `/api/summary` | Total and per-category counts across all notes |

```json
{"title": "Release checklist", "body": "Review deployment", "category": "work"}
```

Titles allow 1–100 characters, bodies 1–4000, and categories are `work`, `personal`,
or `ideas`. Leading/trailing whitespace is removed. Invalid input, unknown fields,
invalid UUIDs, and search strings over 100 characters return 422.

## Validation

Run the same complete pipeline used by CI:

```sh
bash scripts/check.sh
```

It installs locked dependencies, runs Python lint/format/type checks and tests,
runs frontend type checks and tests, validates Terraform with a mocked provider,
builds the release, then starts the extracted release and tests it over HTTP.
No Azure resources are created. The smoke test binds only to loopback and removes
its temporary files and process on exit. Build outputs and tool caches are ignored
by Git.

Individual checks:

```sh
uv run --project backend --locked ruff check --config backend/pyproject.toml backend scripts
uv run --project backend --locked ruff format --check --config backend/pyproject.toml backend scripts
(cd backend && uv run --locked mypy && uv run --locked pytest)
npm run typecheck --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
bash scripts/check-infra.sh
```

Terraform checks run `fmt -check`, `init -backend=false -lockfile=readonly`,
`validate`, and `test`. Every provider in the Terraform tests is mocked, including
the test's `apply` operation. These checks exercise resource wiring and invalid
configuration without an Azure subscription, credentials, or remote state.

Python tests cover the domain/service, API lifecycle, validation, configuration,
static serving, and Azure adapter calls/errors with mocked SDK clients. Frontend
tests cover HTTP requests, components, application flows, failed requests, safe
text rendering, and out-of-order responses. The release smoke test covers the
assembled frontend assets and backend note lifecycle.

## Release and Azure deployment

Create a ZIP for App Service:

```sh
python3 scripts/build_release.py
uv run --project backend --locked python scripts/smoke.py dist/fieldnotes.zip
```

The ZIP contains `fieldnotes/*.py`, `fieldnotes/static/*`, and a hashed, locked
`requirements.txt` exported from uv. File ordering, timestamps, and permissions
are fixed. Repeated builds with the same toolchain and inputs produce the same
archive. App Service's deployment build installs the production requirements;
its startup command launches `uvicorn` on port 8000. The frontend is built locally,
so Azure does not need Node.js to build this release.

Provisioning and deployment are separate, explicit operations. They require the
Azure CLI, an authenticated account, a subscription, and permissions to create
resources and assign roles. B1 App Service and Storage incur Azure charges.

```sh
cp infra/environments/dev/terraform.tfvars.example infra/environments/dev/terraform.tfvars
# Edit name_suffix to make the storage account and app names globally unique.
az login
export ARM_SUBSCRIPTION_ID="your-subscription-id"
terraform -chdir=infra/environments/dev init
terraform -chdir=infra/environments/dev plan -out=dev.tfplan
terraform -chdir=infra/environments/dev apply dev.tfplan

python3 scripts/build_release.py
az webapp deploy \
  --resource-group "$(terraform -chdir=infra/environments/dev output -raw resource_group_name)" \
  --name "$(terraform -chdir=infra/environments/dev output -raw web_app_name)" \
  --src-path dist/fieldnotes.zip --type zip
terraform -chdir=infra/environments/dev output -raw app_url
```

The dev environment uses local Terraform state; keep it private and retain it for
resource management. Managed identity role assignments may take a few minutes to
propagate. The App Service is not usable until the release ZIP is deployed.
Actual Azure provisioning is separate from local validation.

Azure configuration follows the provider's [Linux web app resource](https://registry.terraform.io/providers/hashicorp/azurerm/4.64.0/docs/resources/linux_web_app)
and [storage container resource](https://registry.terraform.io/providers/hashicorp/azurerm/4.64.0/docs/resources/storage_container).
Credential-free infrastructure tests use [Terraform provider mocking](https://developer.hashicorp.com/terraform/language/tests/mocking).

## Layout

```text
.github/workflows/ci.yml       Local checks run in GitHub Actions
backend/
  src/fieldnotes/              Routes, models, configuration, service, repositories
  tests/                      API, service, configuration, and Azure adapter tests
  pyproject.toml, uv.lock      Python dependencies and check configuration
frontend/
  src/components/             Note form and note list
  src/                        API client, types, app coordinator, styles
  tests/                      Client, component, and application tests
  package*.json               Node dependencies and lockfile
  tsconfig.json, vite.config.ts
infra/
  modules/{resource-group,storage,web-app}/
  environments/dev/           Composition, variables, outputs, provider lockfile
    tests/dev.tftest.hcl      Mocked provider tests
scripts/                      Development, checks, packaging, and smoke test
AGENTS.md                     Repository development instructions
```
