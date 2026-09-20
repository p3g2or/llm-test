# Development

- Keep changes focused and follow the existing Python, TypeScript, and Terraform structure.
- Use Python 3.12, Node 26, uv, and the Terraform version in `.terraform-version`.
- Install locked dependencies with `uv sync --project backend --locked` and `npm ci --prefix frontend`.
- Run `bash scripts/check.sh` before submitting changes. Azure credentials are not needed.
- Keep HTTP handlers small; put note behavior in the service and persistence in repositories.
- Keep the frontend API types and runtime configuration consistent with the backend.
- Add tests for behavior changes. Use in-memory storage or mocked Azure clients in tests.
- Keep dependency lockfiles in sync with dependency declarations.
- Do not commit secrets, Terraform state, generated assets, or local configuration.
- Do not provision cloud resources, commit, or push unless explicitly requested.
