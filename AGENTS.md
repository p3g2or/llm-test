# Development

- Handle change; do not prevent it. Expected changes to prompts, configuration, tools, or saved results should produce clear warnings and recoverable behavior, not block the workflow. Stop only when an operation cannot run, would lose data, or would require presenting an invalid result as valid; limit failures to the affected operation.
- Keep the benchmark standard-library Python and shell, with minimal changes.
- Use Node 26 for Field Notes as pinned in `scenarios/field-notes/baseline/.node-version`.
- Run `bash scripts/check.sh`; never run paid model calls for verification.
- If sandbox restrictions block full validation, report the limitation and run applicable offline tests with Python 3.12. Do not repeatedly retry known permission failures.
- Preserve scenario baselines and keep benchmark metadata outside them.
- Do not provision resources, commit, push, or rewrite history unless requested.
- Never hard-wrap prose in Markdown: keep each paragraph on a single source line and let the editor wrap it visually. Preserve structural line breaks in lists, tables, and code blocks.
