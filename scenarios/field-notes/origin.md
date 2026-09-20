# Field Notes: original creation prompt

This is the original prompt submitted to Codex on 2026-09-17 to create the application that became Field Notes. It requested a working application with passing local checks, before any benchmark tasks or intentional defects were added. The prompt is reproduced verbatim below; it describes the initial request, not every detail of the current baseline. Later changes are summarized in [HISTORY.md](../../HISTORY.md).

```text
Create a small but realistic repository for benchmarking AI coding agents.

The repository will be reused unchanged as a baseline to compare different
coding models, so reproducibility and realistic cross-file dependencies are
important.

Build a small Azure-based web application with three main components:

1. Terraform infrastructure
   - Use reusable Terraform modules.
   - Include an Azure Resource Group.
   - Include a Storage Account.
   - Include infrastructure for hosting a small web application.
   - Create a dev environment that consumes the modules.
   - Use variables, outputs, locals and sensible validation.
   - Do not require actual Azure credentials to run static validation.

2. Python backend
   - Build a small REST API.
   - Keep the application simple but realistic.
   - Include several endpoints and a small service/domain layer.
   - Include interaction with Azure Storage behind an abstraction so tests
     do not require Azure.
   - Add unit tests.
   - Add linting/type-checking configuration where appropriate.

3. JavaScript or TypeScript frontend
   - Build a minimal frontend consuming the backend API.
   - Keep dependencies reasonably small.
   - Include multiple components/modules rather than putting everything in
     one file.
   - Add unit tests.

Also include:
- a few useful shell or Python scripts;
- CI configuration that validates/tests all three parts;
- README.md explaining the architecture and local validation commands;
- AGENTS.md containing only normal repository development instructions,
  not benchmark-specific hints.

Important constraints:

- Keep the repository small enough that an AI coding agent can understand
  the whole project without excessive context usage.
- Prefer simple implementations over frameworks or abstractions that do not
  add value.
- Make the code internally consistent and fully working.
- Do not intentionally introduce bugs yet.
- Do not create benchmark tasks or solutions yet.
- Do not mention expected future modifications in comments or documentation.
- Make cross-component relationships realistic so future tasks can require
  changes across Terraform, Python and JavaScript/TypeScript.
- All tests and static checks should pass in the initial baseline.

After implementation:
1. Run all tests and static validation that can run locally.
2. Fix any failures.
3. Show the final repository structure.
4. Summarize the validation commands and their results.
5. Do not make any further changes after establishing the clean baseline.
```
