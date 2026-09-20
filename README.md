# Coding Models: Task Cost and Quality

Compare what coding models deliver, how well they do it, and what each attempt costs.

**How much useful coding work do you get for your money?** This project compares models on complete development tasks: what they deliver, how well they solve the problem, how long they take, and what the attempt costs. The goal is to estimate **task/$ together with quality**, beyond token/$ pricing. A low token price is only one part of the cost of getting a task done.

## Published results

Start with the three task reports. Each includes a model comparison table with quality, coding time and observed API cost, followed by the findings behind the scores.

| Task and report | What it tests | Published attempts |
|---|---|---:|
| [Fix incorrect counts after deletion](evaluations/field-notes/known-bug/comparison.md) | Diagnose and repair a real concurrency bug. | 9 |
| [Investigate a false category-mixing report](evaluations/field-notes/false-category-mixing/comparison.md) | Check whether a reported bug exists and distinguish it from a separate defect. | 10 |
| [Add a configurable note limit](evaluations/field-notes/note-limit/comparison.md) | Deliver a feature across infrastructure, backend and frontend. | 13 |

The saved attempts illustrate why task outcomes matter: several models fixed the deletion bug but provided different strengths of regression evidence; a plausible false report led some models to overstate what they had found; the note-limit task exposed gaps that passing checks alone did not settle. Read the individual reports for the evidence and limitations, rather than treating the scores as a general model ranking.

The reports currently show **cost per attempt**, not a measured long-run rate of successful tasks per dollar. They help estimate that tradeoff; they do not yet include repeated trials or the cost of human review and follow-up repairs. The USD column covers candidate API calls, not evaluator usage or local compute.

## Why this exists

The idea came from [OpenRouter Ori Eval](https://openrouter.ai/blog/announcements/ori-eval/): compare models on work that matters to your own project. In my experience, the cost and friction of getting Ori working for this experiment motivated a smaller custom system with explicit steps and inspectable saved results. This repository implements that workflow independently; Ori is not required to run it.

## How it works

The test application is **Field Notes**, a small notes app with a Python backend, TypeScript frontend and Terraform configuration. I chose Terraform, Python and TypeScript because they are the technologies I work with most day to day: this benchmark is tailored to my own work. Use it as a starting point, and build your own tasks around the languages, systems and decisions that matter to you.

Field Notes was created with Codex from an [initial application-generation prompt](scenarios/field-notes/origin.md). The request was for a small, realistic Azure application with cross-component dependencies and passing local checks, without intentional bugs or benchmark tasks. The summary bug and the three task prompts were added later. Models now work on separate copies of the selected application baseline.

1. **Choose a task and model.** The runner supplies the task prompt and application source to a coding agent. Each attempt gets a fresh, isolated workspace without previous results, private evaluation guidance or the original Git history.
2. **Let the model investigate and work.** It can read files, change code and run tools through OpenCode. The runner records the conversation, final patch, elapsed time and available API accounting. Attempts run sequentially.
3. **Check the resulting code independently.** After the agent finishes or times out, a separate process runs the project's checks. A passing check is evidence, not proof that the requested task was completed.
4. **Assess the saved work.** An evaluator reads the task, patch, logs and other evidence. It records findings on correctness, testing, scope and diagnosis without executing candidate code.
5. **Compare the attempts.** A synthesis combines the assessments into a report, assigning one holistic quality score from 0 to 100 per attempt. Quality, time and cost remain separate so you can judge the tradeoff yourself.

Coding runs use paid OpenRouter API calls. Evaluation uses Codex with ChatGPT login by default, with an optional paid OpenRouter backend. The orchestration code uses standard-library Python and shell.

## Reading the results

- **Quality is a judgment of the work.** It reflects the six narrative findings, independently of price and speed. A well-supported no-change conclusion can be appropriate; a timeout is not automatically a zero.
- **Failures remain visible.** Failed and timed-out attempts can appear in the reports. Missing measurements stay unknown; incomplete cost accounting is shown as a lower bound rather than an invented total.
- **Historical inputs differ.** Some attempts used different prompts, baselines or evaluator settings, and some original inputs are unavailable. These are individual experiments; small score differences are not statistically established advantages.
- **Published assessments are reusable, but not a complete evidence archive.** They contain findings, citations and available input metadata. Raw patches and logs stay local, so a public checkout cannot independently verify every historical claim.

## Run your own comparison

### Prerequisites

The coding runner requires **macOS with `sandbox-exec`**, Git, uv, Python and OpenCode on PATH. Reading the published reports needs none of these tools.

Authenticate coding runs with `OPENROUTER_API_KEY` or `opencode auth login`. For the default evaluator, use `codex login` with a ChatGPT account.

The runner prepares Node automatically. Terraform must be installed; set `BENCHMARK_TERRAFORM_BIN` if it is not installed under tfenv. Internet access is needed for dependency downloads and model calls. The benchmark does not provision cloud resources.

The macOS requirement comes from filesystem isolation: candidates cannot read private guidance, earlier results or personal files. Network access remains enabled for dependencies.

### Run a coding task

```sh
./benchmark.sh sol --dry-run           # prepare only; no model calls
./benchmark.sh sol --task known-bug    # paid coding attempt
./benchmark.sh all --task note-limit   # paid attempt for every configured model
./benchmark.sh                         # choose a model interactively
```

`known-bug` is the default task. The scenario contains the three built-in task prompts. `config/models.toml` maps aliases to exact model IDs and optional provider pins. Unavailable models fail explicitly; they are never silently substituted.

Runs always go to `results/`; reports go to `evaluations/`. There are no external task-file or custom results-directory options. New attempts preserve earlier ones.

## Evaluate and resume

### Create or update a report

```sh
./evaluate.sh field-notes/known-bug --dry-run  # inspect the plan; no writes or model calls
./evaluate.sh field-notes/known-bug           # assess new work and update the report
./evaluate.sh all                            # update each task's report separately
```

The evaluator shows which assessments and synthesis calls are needed, then asks for confirmation if model calls are required. Repeating the same command resumes saved progress. An unchanged report can be regenerated without model calls, confirmation or an interactive terminal.

### What gets reused?

| Situation | Behavior |
|---|---|
| Nothing changed | Reuse the assessments and synthesis; regenerate Markdown if needed. |
| A model has a new finished local attempt | Assess that attempt and rebuild the comparison synthesis. |
| A new model is added | Assess the new model and combine it with existing assessments. |
| Evidence for a selected attempt changed | Reassess only that attempt, then update the synthesis. |
| A published model has no local results directory | Keep its published assessment; original evidence is not required for synthesis. |
| Evaluation was interrupted | Continue from the last saved assessment or synthesis. |

Local selection follows each model's `latest` pointer, including failed and timed-out attempts. Missing, unfinished or dry-run latest attempts are skipped with a warning; the evaluator does not silently fall back to an older successful attempt. A local model directory takes precedence over its published assessment.

Before replacing reports, the evaluator backs them up under the task's `history/` directory. JSON progress is saved atomically after each completed assessment. The ignored `.checkpoint.lock` file prevents concurrent writers to the same comparison.

### Evaluator settings

| Backend | Authentication and configuration |
|---|---|
| **Codex — default** | ChatGPT login; low reasoning effort; 900-second session timeout. `--model MODEL` and `--timeout SECONDS` override the model and timeout. `config/evaluator.toml` is not read. |
| **OpenRouter — optional** | Select with `--backend openrouter`; uses paid API calls and `config/evaluator.toml`. `--config FILE` selects another configuration; `--model` and `--timeout` override its values. |

Changing evaluator settings affects new calls. Saved judgments retain the settings and provenance under which they were produced.

### Changed or missing inputs

Prompt, baseline and guidance changes produce warnings rather than blocking the workflow. Saved prompts take precedence over current instructions. Missing optional evidence is marked missing; unavailable historical source may be replaced by clearly identified current reference material.

Each published assessment retains the available original baseline hash in `benchmark_inputs.baseline_sha256`. A different hash does not prevent comparison. The hash identifies historical bytes but cannot reconstruct them: independent reassessment of an old attempt requires its original evidence, not just the published findings. Input differences are reported in terminal warnings and saved metadata rather than repeated in the Markdown comparison.

## Files and provenance

Published reports live under `evaluations/<scenario>/<task>/`:

| File | Purpose |
|---|---|
| `comparison.md` | Readable comparison: summary, quality/time/cost table and per-model findings. |
| `comparison.json` | Reusable assessments, synthesis, evaluator provenance, available prompts/guidance, baseline hashes and resume state. |

Local attempts live under `results/<scenario>/<task>/<model>/runs/<id>/`; `latest` points to the latest finished attempt.

| File | Purpose |
|---|---|
| `run.json` | Exact prompt, prompt version when known, effective guidance, baseline hash and execution settings. |
| `metrics.json` | Status, independent validation, durations, observed usage and cost. |
| `diff.patch` | Final changes, including added files and binary patches. |
| `response.txt` | Final model response. |
| `check.log` | Independent validation output. |
| `transcript.jsonl` | Detailed model and tool evidence. |
| `api-calls.json` | Per-call usage, billing and observed model/provider data. |
| `opencode.log` | CLI stderr, when nonempty. |

`results/`, report backups and private archives under `.local/` are excluded from Git. Raw transcripts, including opaque encrypted reasoning, stay local. Published evidence citations refer to these local artifacts; published run references are repository-relative so they survive cloning elsewhere.

Costs use returned API accounting rather than token-price estimates. Coding time and independent validation time are recorded separately. The baseline archive is built in memory from scenario source; its saved SHA-256 does not preserve a historical source snapshot. Missing historical hashes remain null, and legacy artifact copies remain readable.

## Development and checks

```sh
python3 -m unittest discover -s tests -v -b
bash scripts/check.sh
BENCHMARK_INTEGRATION=1 bash scripts/check.sh  # also run the three opt-in integration tests
```

The full script runs harness tests, Ruff, baseline tests/build/smoke checks and a disposable-copy defect check. The integration tests use real OpenCode and a fake local API; checks never call paid models.

The defect check deliberately verifies that the baseline still contains the benchmark bug, then applies a known fix to an expendable copy. Its `Known-fix control: defect assertion correctly fails...` message is expected: the assertion that the bug exists should fail after correction. The preserved baseline is unchanged.

## License

The project code and accompanying documentation, including the published comparisons, are licensed under the [MIT License](LICENSE). Third-party dependencies retain their own licenses.
