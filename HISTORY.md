# History

## 2026-09-20

Prepared a public snapshot with a fresh Git history. The earlier repository and raw results are retained in a private local archive. Raw results remain local; published comparisons retain their saved findings, evaluator provenance, available input metadata and original baseline hashes. Run references are repository-relative. Existing published assessments can be reused and extended without the original results, but independent reassessment of historical claims still requires their original evidence. Baseline changes warn rather than blocking comparison. Historical hashes identify inputs; they do not reconstruct missing source bytes.

Simplified the experiment harness: built-in tasks and fixed `results/` and `evaluations/` directories only. Ordinary input and tool changes now warn instead of blocking unrelated work. Evaluation reuses valid assessments, rebuilds changed stages and preserves previous reports before replacement. Documentation is consolidated in README; historical notes no longer control execution.

Known-bug prompt v1 explicitly requested regression coverage and avoidance of unrelated changes. Version v2 keeps the same bug description but asks only to investigate and fix it. Seven imported attempts (Astra, Auto, DeepSeek, Gemini, MiMo, Opus and Qwen) used v1; GLM and the new Sol run used v2. The import retained the latest historical attempt, including failed Gemini. Imported baseline hashes describe the original runs; the current baseline is reference material, not a recovered historical snapshot. Historical guidance was not recovered. Exact prompts and available provenance remain in run metadata.

## 2026-09-19

A publication audit anonymized local paths and removed opaque encrypted reasoning payloads from a saved-results snapshot while retaining readable reasoning, patches and measurements. Historical evaluation hashes can therefore refer to earlier bytes. The audit was limited to that snapshot; its inventory is not a current repository manifest.

A one-off false-category-mixing review used weighted scoring that included time and cost. That experimental report and its publication inventory have been retired. Current comparisons use six narrative findings and a holistic quality score independent of time and cost; earlier scores are not interchangeable with these judgments.

## 2026-09-18

Added the known-bug, false-category-mixing and note-limit tasks, isolated candidate execution and private evaluation guidance. Field Notes moved to the pinned Node 26 toolchain. Later result storage was simplified to per-model runs with a latest pointer; effective inputs and provenance belong to run metadata rather than operational migration documents.
