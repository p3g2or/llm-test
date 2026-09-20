# Benchmark comparison

## Summary

astra provides the strongest regression coverage; auto, deepseek, glm, opus, and qwen also deliver focused fixes with demonstrated failure before correction. mimo and sol deliver correct fixes with narrower validation, while gemini identifies the cause but leaves the repair unfinished.

| Model | Quality (0–100) | Time(s) | USD |
|---|---:|---:|---:|
| astra | 99 | 171 | $0.8503 |
| auto | 92 | 121 | $0.0358 |
| deepseek | 90 | 154 | $0.0258 |
| gemini | 45 | 900 | >=$0.1826 (incomplete) |
| glm | 93 | 440 | $0.0383 |
| mimo | 88 | 98 | $0.0112 |
| opus | 95 | 118 | $0.3865 |
| qwen | 93 | 222 | $0.1845 |
| sol | 88 | 124 | $0.2055 |

## astra

The candidate correctly diagnosed and fixed the reported stale-summary race, with regression coverage explicitly required by the saved task. Moving the revision guard before both DOM updates prevents outdated counts from winning while preserving existing error and busy-state protection. Both deferred-response cases failed before the fix; saved validation passed 17 frontend tests, 31 backend tests, infrastructure checks, build, and smoke coverage. Changes stayed within the application and its tests, with no weakened checks; unsuccessful patch-tool attempts were brief environment recovery. No separate independent bug was established in the reviewed evidence. The candidate identified the precise guard-ordering defect and reproduced stale total and category counts after deletion.

## auto

The candidate correctly diagnosed and fixed the reported stale-summary race with a minimal guard relocation and useful regression coverage. The patch guards both summary and list updates, while saved validation reports PASS with 16 frontend tests and 31 backend tests. Recorded rollback fails and restoration passes; coverage omits final list preservation and exact category counts, and test comments misdescribe asynchronous refresh ordering. Changes remain limited to the frontend guard and one regression test, with no weakened checks or unrelated modifications. No additional independent bug discovery is established by the reviewed evidence. The response explicitly identifies older refreshes overwriting summary counts before the revision guard, matching the reported defect.

## deepseek

The candidate correctly diagnosed and fixed the reported stale-summary race, with useful regression coverage and a completed, usable handoff. The guard now protects both summary and list updates while preserving existing error and busy-state guards; saved validation passed. Saved reversal testing demonstrates failure before correction and success afterward, but the regression omits deletion, category-count assertions, and list assertions. Changes remain limited to the frontend guard and one regression test, without dependencies, unrelated edits, or weakened checks. No separate independent bug was established in the reviewed evidence. The candidate explicitly identified the summary mutation preceding the revision check and connected overlapping refreshes to the reported count corruption.

## gemini

The run timed out without a patch or final response, leaving the requested deletion-count fix incomplete. Saved validation passed on unchanged code; this establishes baseline check success, not correction of the reported stale-summary behavior. No regression coverage was added; the existing outdated-response test checks note text but does not assert that summary counts remain current. No files changed, so there is no evidence of unrelated modifications or weakened validation. No additional independently confirmed issue is established by the reviewed evidence. The candidate correctly identified that summary updates precede the revision guard, allowing older refreshes to overwrite current counts, but never implemented a correction.

## glm

The candidate correctly diagnosed and fixed the reported stale-summary race, retained regression coverage, and completed a successful handoff. Moving the revision guard before summary updates protects both rendered results while preserving existing error and busy-state guards. Saved evidence establishes baseline-red/fix-green; the regression checks total and work counts but omits list preservation, other categories, and stale error/busy assertions. Only application logic and its regression test changed, although repeated quoting and working-directory mistakes caused avoidable retries. No separate independent bug was established in the reviewed evidence. The candidate explicitly identified the summary mutation preceding the stale-response guard and connected it to overlapping refreshes.

## mimo

The candidate correctly fixed the reported stale-summary race and supplied useful, though incomplete, regression coverage requested by the saved task. The retained guard relocation protects both DOM updates; saved validation passed backend/frontend tests, typechecking, infrastructure checks, build, and release smoke. Deferred responses exercise stale total overwrites, but assertions omit category counts, list preservation, and deletion; no baseline-red execution is recorded. The final two-file patch is focused, but failed editing approaches temporarily mangled and emptied the source before recovery. No separate independent bug was established in the reviewed evidence. The candidate explicitly identified summary mutation preceding the revision guard and explained why stale counts survive while outdated list updates are discarded.

## opus

The candidate correctly fixed the reported stale-summary race and supplied regression coverage explicitly requested by the saved historical task. The guard now protects both DOM updates; saved validation reports 31 backend tests, 16 frontend tests, infrastructure checks, build, and smoke passing. Controlled stale-summary completion demonstrably fails without the fix and passes with it, but the new regression omits list, stale-error, and busy-state assertions. Only application guard ordering and one regression test changed, although repeated failed temporary-file edits introduced avoidable tool churn. No separate independent bug was established in the reviewed evidence. The candidate identified summary mutation before the revision check as the cause and confirmed the resulting incorrect counts through a failing regression.

## qwen

The candidate correctly diagnosed and fixed the reported stale-summary race, adding the regression coverage explicitly required by the saved task. The revision guard now protects both summary and list updates; saved validation reports passing backend, frontend, infrastructure, and smoke checks. The regression demonstrably fails without the fix and passes with it, but omits explicit empty-list and complete category-count assertions. Changes stay within the frontend refresh guard and regression test, preserving existing checks and using a saved patch during temporary reversion. No additional independent bug discovery is established by the reviewed evidence. The candidate identified the exact ordering defect: an outdated response updated summary counts before reaching the existing stale-response guard.

## sol

The candidate correctly fixed the reported stale-count race with a minimal change and useful, though incomplete, regression coverage. The guard now protects both DOM updates; saved validation passed 31 backend, 16 frontend, and four Terraform tests, plus typecheck, build, and smoke checks. The deferred-summary regression exercises stale completion but checks only total count, omitting deletion, category counts, and list assertions; baseline failure was not demonstrated. Changes are limited to the refresh guard and one regression test, preserving existing error and busy-state protection without weakening validation. No additional independent bug was established in the reviewed evidence; provenance matches this run, so historical migration limitations do not affect this assessment. The candidate identified the precise ordering defect before editing: outdated refreshes mutated summary counts before the revision guard discarded their note lists.
