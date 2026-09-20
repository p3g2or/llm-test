# Benchmark comparison

## Summary

Astra delivered a completed summary-race repair with failing-before/passing-after regressions; Kimi delivered a more minimal repair with similar evidence but timed out before handoff. Auto and Mimo completed correct summary repairs with weaker testing and overstated category-mixing claims, while Gemini gave a defensible source-based no-change explanation without a targeted reproduction.

| Model | Quality (0–100) | Time(s) | USD |
|---|---:|---:|---:|
| astra | 84 | 184 | $1.2736 |
| auto | 66 | 59 | $0.0155 |
| deepseek | 46 | 900 | >=$0.0431 (incomplete) |
| gemini | 78 | 784 | $1.2186 |
| glm | 45 | 900 | >=$0.0614 (incomplete) |
| kimi | 86 | 900 | $2.3970 |
| mimo | 60 | 136 | $0.0109 |
| minimax | 20 | 93 | $0.0258 |
| opus | 25 | 900 | >=$3.1769 (incomplete) |
| qwen | 48 | 900 | >=$0.4788 (incomplete) |

## astra

The candidate repaired the independent stale-summary race, but did not establish the reported coexistence of notes from different categories. Moving the revision guard protects both summary and list updates while preserving existing error and busy-state guards. Saved tests demonstrate baseline failures followed by seven passing application tests; stale rejection ordering and complete category-count assertions remain uncovered. Changes stayed within two frontend files, although clearing results on every refresh exceeds the proven race fix and repeated patch attempts reduced efficiency. Previous notes remaining during pending or failed refreshes were demonstrated, but this differs from mixed-category coexistence and involves a loading-behavior choice. The candidate explicitly identified and repaired the separate stale-summary race before validation, supported by a regression failing on outdated totals.

## auto

The candidate repaired the separate stale-summary race but incorrectly claimed to fix category mixing without establishing that reported behavior. Moving the revision guard before summary updates correctly protects both outputs; clearing results additionally changes loading and failed-refresh behavior. The added category test exercises existing list protection and would pass the baseline; it asserts neither summary freshness nor immediate clearing. Changes stayed within two relevant files, but redundant filter snapshots and unverified clearing behavior exceed the minimal justified repair. The candidate explicitly noticed summary updates preceding freshness validation, providing discovery evidence beyond the patch alone. The known stale-summary defect was identified and repaired, although the handoff conflated it with the false category-mixing report.

## deepseek

The category-mixing report was not reproduced; the candidate recognized a separate summary race but timed out without a completed conclusion or repair. Production code remained unchanged, preserving list isolation and leaving stale summary updates possible. The added deferred-response test verifies category isolation, but omits summary assertions and does not reassert the current note after stale completion. The patch was limited to one test, but repeated speculation and searches beyond project sources prevented timely completion. Transcript reasoning explicitly identifies summary updates before the revision guard as a separate defect. The known stale-summary race was recognized through inspection, without a targeted reproduction or retained fix.

## gemini

The candidate explained existing list isolation and avoided an unjustified patch, but ended with clarification requests rather than a targeted reproduction. The revision guard protects list replacement, while summary updates occur before that guard and remain vulnerable to stale responses. Saved validation passed unchanged tests; existing deferred-response coverage checks outdated note text but neither category mixing directly nor stale summary counts. No changes were retained, but repeated repository inspection and trivial Python output probes substantially diluted the investigation. No separate defect was established in the candidate's handoff. Discovery of the known stale-summary race is not established; quoting the vulnerable code does not demonstrate recognition.

## glm

The mixed-category report was not reproduced; the candidate retained a passing isolation test but timed out without completing the investigation. Production code remained unchanged, preserving correct stale-list rejection and the separate stale-summary defect. The added test checks an older work response completing after personal results, but repeats one ordering and omits summary and intermediate-state assertions. The patch stayed limited to one test, but repeated investigation, unrelated repository reading, and browser searches consumed the available time. Transcript reasoning identified the unguarded summary update as a separate race, without reproducing, repairing, or reporting it in a completed handoff. The candidate noticed the known stale-summary mechanism, but discovery did not become a tested fix.

## kimi

The mixed-category report was not reproduced; the candidate independently found and repaired a stale-summary race but timed out before completing handoff. Moving the revision guard before summary updates correctly protects both summary and list rendering while preserving existing error and busy-state guards. A deferred-summary reproduction failed before correction and passed afterward, but retained assertions cover only total counts, excluding category counts and simultaneous list integrity. The final two-file patch is minimal, but repeated reconsideration, broad searches, and redundant investigations consumed the available time. The candidate demonstrated that an older summary response overwrote newer totals, although its explanation sometimes conflated this separate defect with the reported symptom. The independently reproduced summary race matches the known defect described by current benchmark guidance.

## mimo

The candidate repaired the independent stale-summary race but incorrectly presented unverified category mixing as established. Moving the revision guard protects both summary and list updates; clearing results additionally changes loading and failure behavior without demonstrated necessity. Saved validation passed existing checks, including 15 frontend tests, but no added regression demonstrated baseline failure and corrected summary behavior. The final patch was small, but unnecessary clearing and failed whole-file rewrites reduced discipline; temporary file truncation was repaired. The candidate explicitly identified older responses overwriting summary counts before the revision check and repaired that separate defect. Discovery of the benchmark’s stale-summary defect is supported by the explanation and guard relocation, independently of validation PASS.

## minimax

The candidate noticed existing stale-list protection but stopped before reproducing the report or delivering a supported conclusion. Source inspection supports list isolation; the separate stale-summary race remains unchanged. Saved validation passed existing tests, but the candidate performed no reproduction, added no assertions, and supplied no regression evidence. No files changed or checks were weakened, but repetitive malformed reasoning prevented completion. No separate defect discovery was established in the reviewed candidate evidence. The candidate quoted the vulnerable summary assignment without identifying its stale-response consequence.

## opus

The investigation found evidence against category mixing but timed out without a conclusion, leaving a test that breaks type checking. The verified baseline guards stale note lists and replaces their contents; the retained change does not alter production behavior. Saved experiments observed list isolation and zero backend mismatches, but the retained randomized test asserts only true and never checks summary correctness. Production changes were avoided, but repeated speculative investigation continued after contrary evidence and left unfinished experimental code. Reasoning identified the unguarded summary update as a separate stale-count risk, without reproducing, repairing, or reporting it. The stale-summary defect was noticed internally, but discovery did not become a validated finding or delivered fix.

## qwen

The investigation found evidence against category mixing and noticed the separate summary race, but timed out without a completed conclusion. The unchanged list guard correctly rejects outdated results; saved validation passed, while the summary still updates before the guard. Temporary deferred-response and seeded interaction tests passed, but allowed empty results, omitted summary assertions, and were removed. No production changes were made, but repeated speculative investigation expanded into build and CI files without resolving the report. Internal reasoning explicitly identified stale responses overwriting summary counts and distinguished this defect from the alleged mixed-category list. The known summary race was recognized but neither reproduced with targeted assertions, repaired, nor communicated in a completed handoff.
