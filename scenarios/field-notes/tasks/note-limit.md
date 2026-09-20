Add support for a configurable maximum number of notes.

The limit must be configurable from the Terraform dev environment and enforced by the backend.

The frontend should show users the configured limit and prevent creating another note when the limit has been reached.

The application must continue to work when no explicit limit is configured.
