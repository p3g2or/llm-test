# Coding model benchmark

Run coding models on isolated copies of the Field Notes application, then compare their saved results. The harness uses standard-library Python and shell. Coding runs use paid OpenRouter calls; evaluation uses Codex with ChatGPT login by default.

## Setup

Use macOS with `sandbox-exec`, Git, uv, Python 3.12 (`uv python find --offline 3.12`), and OpenCode on PATH. OpenCode 1.18.30 is the tested version; other versions produce a warning. Authenticate with `OPENROUTER_API_KEY` or `opencode auth login`. Evaluation requires `codex login` with a ChatGPT account.

The runner stages the Node version from `scenarios/field-notes/baseline/.node-version`. Terraform must match the baseline's `.terraform-version`; set `BENCHMARK_TERRAFORM_BIN` if it is not installed under tfenv. Internet access is needed for dependencies and real model calls. Nothing provisions cloud resources.

The coding runner requires macOS because its filesystem isolation uses `sandbox-exec`. This keeps private guidance, previous results and personal files outside the candidate workspace. Network access remains enabled for dependency downloads. Reading published reports does not require macOS or model access.

## Run

```sh
./benchmark.sh                         # choose a model interactively
./benchmark.sh sol --task known-bug    # paid coding run
./benchmark.sh all --task note-limit   # new independent run for every model
./benchmark.sh sol --dry-run           # preparation only, no model calls

./evaluate.sh field-notes/known-bug --dry-run  # inspect required evaluation work
./evaluate.sh field-notes/known-bug           # resume or update comparison
./evaluate.sh all                            # separate comparison for each task
```

Aliases and exact model IDs are in `config/models.toml`. An unavailable model is recorded as failed; it is never replaced by another model. Optional provider pins are in the same file. Candidates receive the task text and baseline in isolated temporary repositories without benchmark guidance, results, or original Git history. Dependency downloads are allowed. Independent checks run after each coding attempt, including failed or timed-out attempts.

Built-in Field Notes tasks:

| Task | Description |
|---|---|
| `known-bug` (default) | Investigate incorrect totals and category counts after deletion. |
| `false-category-mixing` | Investigate an intentionally false report; the separate summary bug remains. |
| `note-limit` | Add a configurable note limit through Terraform, backend and frontend. |

Task prompts are in `scenarios/field-notes/tasks/`; task configuration is in `scenario.toml`. There are no external task-file or custom results-directory options. Results always go to `results/`; reports go to `evaluations/`.

## Evaluate and resume

The evaluator selects each model's latest finished attempt, including failed and timed-out attempts. Missing, unfinished and dry-run latest attempts are skipped with a warning; it does not silently choose an older successful run. An unavailable optional evidence file is marked missing.

Published `comparison.json` files also work without the local `results/` directory. Existing assessments are retained when their model has no local results directory; a new local attempt for that model replaces its published assessment. New models are assessed from their local evidence and added to the comparison. The synthesis uses saved assessments, so it can combine published and newly assessed runs. Rebuilding an unchanged Markdown report requires no model calls. Reassessing an old attempt from its original code and logs requires the original local results; the published findings alone cannot establish those claims independently.

Changes are handled, not prohibited. Prompt, baseline and guidance differences produce terminal warnings. Prompt versions and differences are not added to the Markdown report. Saved prompts take precedence over current instructions. Where historical source is unavailable, current source is identified as reference material and conclusions must reflect that limitation.

Unchanged assessments are reused. Adding or rerunning a model evaluates only the new attempt and updates the synthesis. Changed evidence invalidates only the affected assessment. Evaluator setting changes apply to new calls; existing judgments keep their original provenance. The plan lists the required calls and asks for confirmation only when model calls are needed. Regenerating a completed report requires neither confirmation nor a terminal. `--dry-run` never changes saved work or calls a model.

Before rebuilding a comparison, existing reports are copied into its `history/` subdirectory. The current JSON is saved atomically after each completed assessment. Repeat the same command after interruption. Old backup folders may be removed when no longer needed.

`--model MODEL` selects an evaluator model; `--timeout SECONDS` sets the session timeout (default 900). Codex uses low reasoning effort. The optional `--backend openrouter` uses paid API calls and defaults from `config/evaluator.toml`; `--config FILE` overrides that evaluator configuration.

## Saved files

Runs live at `results/<scenario>/<task>/<model>/runs/<id>/`; `latest` points to the latest finished attempt. New runs never overwrite old ones.

`results/` is local and excluded from Git, as are report backups in `evaluations/**/history/`. Private repository archives and earlier generated artifacts live under the ignored `.local/` directory. Only the task comparisons in `evaluations/` are published. Raw transcripts, including opaque encrypted reasoning, stay local. New benchmark runs create their own local results. Published comparisons retain findings, evidence citations, model identities, cost/time measurements, evaluator provenance, available saved prompts/guidance and baseline hashes. Evidence citations name local artifacts that are not included in the public repository.

| File | Purpose |
|---|---|
| `run.json` | Exact prompt, prompt version when known, effective guidance and execution settings. |
| `metrics.json` | Status, independent validation, durations, observed usage and cost. |
| `diff.patch` | Final changes, including added files and binary patches. |
| `response.txt` | Final model response. |
| `check.log` | Independent validation output. |
| `transcript.jsonl` | Detailed model/tool evidence. |
| `api-calls.json` | Per-call usage, billing and observed model/provider data. |
| `opencode.log` | CLI stderr, only when nonempty. |

The baseline archive is built in memory from scenario source; its hash identifies it but does not preserve historical bytes. Older runs without saved guidance may use current guidance as explicitly unverified reference. Legacy artifact copies remain readable.

The recorded baseline SHA-256 is also retained as `benchmark_inputs.baseline_sha256` in each assessment; unavailable historical hashes remain null. Hash differences produce warnings, never a blanket refusal to compare runs. Published run references are relative to the repository and remain usable after cloning elsewhere.

Missing measurements are unknown, never invented zeros. Costs come from returned API accounting, not price estimates; incomplete costs are lower bounds. Coding and validation times are separate. Validation PASS alone does not establish task success.

Each task has `evaluations/<scenario>/<task>/comparison.json` (assessments and resumable state) and `comparison.md` (generated report). Quality is a holistic 0–100 judgment of the six narrative findings, independent of time and price. Evaluation reads evidence; it does not execute candidate code. Evaluator instructions are in `scenarios/field-notes/evaluation/`.

These are individual experimental attempts, not a general model ranking. Historical attempts can have different prompts, baselines and evaluator settings; some original inputs are unavailable. Scores are subjective judgments, and small differences should not be treated as statistically established advantages. See `HISTORY.md` for the known historical limitations.

## Development

```sh
python3 -m unittest discover -s tests -v -b
bash scripts/check.sh
```

Use Python 3.12 and the baseline-pinned Node runtime for local checks. The full script runs harness tests, Ruff, baseline tests/build/smoke checks, and a disposable-copy defect check. `BENCHMARK_INTEGRATION=1` enables the real OpenCode integration test against a fake local API. Checks never call paid models. The scenario baseline remains the benchmark input, including its own application README and tests.

See `HISTORY.md` for changes that affect historical results. Development instructions are in `AGENTS.md`.

## License

The project code and accompanying documentation, including the published comparisons, are licensed under the [MIT License](LICENSE). Third-party dependencies retain their own licenses.
