# Benchmark comparison

## Summary

astra provides the most convincing implementation and regression coverage; qwen and sol are useful but retain testing or state-management gaps. Other attempts leave configuration or frontend defects, while gemini leaves startup broken and the required frontend unfinished.

| Model | Quality (0–100) | Time(s) | USD |
|---|---:|---:|---:|
| astra | 96 | 341 | $3.2673 |
| auto | 60 | 334 | $0.0969 |
| deepseek | 78 | 468 | $0.0392 |
| gemini | 20 | 900 | >=$1.4856 (incomplete) |
| glm | 73 | 900 | $0.0763 |
| kimi | 78 | 545 | $1.1743 |
| mimo | 65 | 280 | $0.0218 |
| minimax | 65 | 900 | >=$0.6480 (incomplete) |
| opus | 69 | 721 | $4.6451 |
| qwen | 85 | 900 | >=$0.7858 (incomplete) |
| qwen-flash | 69 | 900 | >=$0.0639 (incomplete) |
| sol | 82 | 363 | $0.6989 |
| sonnet | 78 | 858 | $2.5791 |

## astra

The implementation appears to satisfy the saved note-limit task across all three layers; baseline provenance is verified, but historical guidance remains unverified. Saved validation passed 49 backend, 21 frontend, and nine Terraform tests, plus build and smoke checks; distributed enforcement is explicitly excluded. Added tests cover configuration, persistence modes, capacity boundaries, deletion recovery, rejected drafts, and response ordering; concurrency coverage uses timing, and category-count assertions remain incomplete. Changes remain focused on the feature, supporting documentation, and tests, with no dependency additions or validation weakening visible in the patch. The candidate anticipated filtered-count mistakes, lowered limits, stale browser capacity, and concurrent creation, adding safeguards and documenting the single-process constraint. The patch fixes the pre-existing stale-summary race and adds a total-count regression assertion, although explicit recognition of the original defect remains unestablished.

## auto

The feature spans all required layers, but frontend prevention fails after filling the last slot because submission cleanup re-enables the button. Sequential backend enforcement and unlimited defaults are implemented; saved validation passed 37 backend, 18 frontend, and six Terraform tests plus release smoke. Added tests cover rejection, deletion recovery, configuration, and isolated button states, but miss the complete frontend save-to-capacity lifecycle and response ordering. Changes remain feature-focused without weakening checks; the baseline is historically verified, while guidance is current-only and historically unverified. Source review additionally finds Terraform accepts fractional limits that backend parsing rejects; candidate recognition of this inconsistency is not established. Discovery of the existing stale-summary race is unestablished; placing capacity updates before the revision guard extends its effects to creation availability.

## deepseek

The requested feature is substantially implemented, but Terraform accepts fractional limits that backend parsing rejects, creating a configuration failure despite passing validation. Source review supports global-count enforcement, unlimited defaults, deletion recovery, and guarded frontend capacity updates; saved validation passed 35 backend, 18 frontend, and six Terraform tests. Added tests cover rejection, configuration, capacity display, and service recovery, but omit fractional Terraform values, concurrent creation, and capacity response ordering. Changes remain focused on the feature, documentation, and tests without weakening checks; baseline provenance is verified, while historical guidance remains unverified. Review identified the fractional-value mismatch; candidate reasoning mentions atomicity, but the separate count and insertion remain unprotected and the handoff documents no concurrency limitation. Discovery of the pre-existing stale-summary race is unestablished: summary updates remain before the revision guard, although new capacity updates correctly follow it.

## gemini

The timed-out attempt leaves the feature incomplete: Terraform and backend changes exist, but required frontend limit display and creation prevention are absent. Saved validation fails on syntax errors in backend configuration and API tests, preventing application startup and successful verification. Six Terraform tests passed; added backend tests cover rejection, deletion recovery, configuration, and Azure counting, but frontend coverage is absent and final checks fail. The configuration rewrite unnecessarily replaces existing conventions, weakens Azure validation, and changes storage-container and static-directory defaults. Review additionally identifies an unprotected count-then-create race; candidate recognition is unestablished, and strict concurrent enforcement was not explicitly required. The existing stale-summary race remains unchanged, with discovery unknown; baseline provenance is verified, while historical guidance is unverified.

## glm

The implementation covers the requested layers, but stale responses can incorrectly enable or disable creation despite passing saved validation. Terraform propagation, unlimited defaults, and sequential backend rejection appear correct; saved checks passed 39 backend, 19 frontend, six Terraform tests, and release smoke. Added tests cover configuration and capacity boundaries, but omit response ordering and concurrency; the deletion-labelled frontend test only changes mocks and submits filters. Changes remain feature-focused without dependency additions or weakened checks; execution timed out before a final handoff, and historical guidance is unverified. The candidate recognized non-atomic check-then-create enforcement but accepted it without safeguards; concurrent requests can exceed capacity. Transcript reasoning explicitly identifies the existing stale-summary race, then deliberately preserves it and extends its effects to the creation button without regression coverage.

## kimi

The requested feature works in ordinary flows across Terraform, backend, and frontend; review found concurrency weaknesses beyond the passing validation. Configuration defaults to unlimited, backend checks global capacity, and frontend blocks full notebooks; concurrent backend creation remains non-atomic. Saved validation passed 37 backend, 18 frontend, six Terraform tests and release smoke; added coverage lacks concurrent creation and stale-response regressions. Changes remain feature-focused without weakened checks; assessment uses the saved task and verified baseline, while current guidance has unverified historical provenance. Review identifies that setFull(false) can re-enable submission during an ongoing save, permitting duplicate requests; this behavior lacks a regression test. The candidate explicitly recognized the pre-existing stale-summary race but deliberately retained it, protecting only the new capacity state from outdated responses.

## mimo

The requested limit works across layers in ordinary use, but review identifies draft loss during refresh and incomplete Terraform validation. Saved validation passed 38 backend, 18 frontend and five Terraform tests, plus release smoke; source supports global capacity checks and unlimited defaults. Added tests cover rejection, deletion recovery, defaults and component rendering, but omit application capacity transitions, draft preservation, fractional configuration and concurrent creation. Changes remain feature-focused without weakened checks; the baseline hash is verified, while current guidance has unverified historical provenance. Review finds refresh replaces unsaved drafts, while Terraform accepts fractional limits that backend integer parsing rejects; candidate recognition of these issues is unestablished. The pre-existing stale-summary race remains without demonstrated discovery or regression coverage, although new capacity updates occur after the revision guard.

## minimax

The feature spans all requested layers, but stale responses can corrupt capacity controls and Terraform accepts fractional limits that prevent backend startup. Saved validation passed 39 backend, 18 frontend, and six Terraform tests plus release smoke; the run timed out with an empty final response. Added tests cover limits, rejection, defaults, deletion recovery, and wiring, but omit fractional configuration, concurrent creation, and outdated capacity responses. Changes remain feature-focused without weakened checks; provenance verifies the historical baseline and saved prompt, while current guidance’s historical applicability remains unverified. The candidate recognized concurrent check-then-create overshoot but accepted it without safeguards; review additionally found Terraform’s integer-validation claim inconsistent with its numeric constraint. The candidate considered outdated totals but incorrectly dismissed the race, leaving the known summary defect intact and extending its effects to creation availability.

## opus

The feature spans Terraform, backend, and frontend, but stale responses can incorrectly enable creation at capacity or block it after deletion. Sequential backend enforcement and unlimited defaults appear correct; saved validation passed 40 backend, 17 frontend, seven Terraform tests, and release smoke. Added tests cover configuration, rejection, and restored capacity, but omit overlapping refreshes and submissions; existing response-ordering coverage checks only note text. Changes remain focused without weakening checks; review uses the verified historical baseline and matching saved task, while current guidance lacks historical verification. The candidate documented non-atomic enforcement; review additionally finds that refreshing counts can re-enable submission during an outstanding save, permitting duplicate requests. Discovery is unestablished: the pre-existing stale-summary race remains, and the new capacity update also executes before the revision guard.

## qwen

The requested feature is substantially implemented across all layers, although the run timed out without a completed handoff. Saved validation passed 41 backend tests, 19 frontend tests, seven Terraform tests, and release smoke; source supports optional limits and creation recovery after deletion. Added tests cover configuration, capacity boundaries, deletion recovery, defaults, and wiring, but omit concurrent creation, stale responses, and cross-tab capacity recovery. Changes remain feature-focused without weakening checks; baseline provenance is verified, while current guidance has unverified historical provenance. The candidate recognized non-atomic enforcement but accepted it without safeguards; concurrent requests can exceed capacity, and rejected submissions do not refresh capacity. The candidate explicitly identified the existing stale-summary race, preserved it, and guarded new capacity updates; no regression test demonstrates the discovery.

## qwen-flash

The feature spans Terraform, backend, and frontend, but stale responses can incorrectly change creation availability; the run timed out before a final handoff. Source review supports optional unlimited defaults and sequential backend enforcement across storage modes; saved validation passed 37 backend, 18 frontend, and seven Terraform tests. Added tests cover configuration, rejection, deletion recovery, and infrastructure wiring, but omit capacity response ordering and concurrent creation. Changes remain focused on the saved feature request without weakening checks; baseline provenance is verified, while historical guidance is unverified. Review identified non-atomic count-then-create enforcement and capacity updates that can re-enable submission during a pending save; candidate recognition is not established. Discovery of the existing stale-summary race is unknown; it remains unfixed and now also affects form capacity because updates precede the revision guard.

## sol

The requested note-limit feature is implemented end-to-end with unlimited defaults; source review identifies a remaining frontend submission-state race. Saved validation passed 36 backend, 16 frontend, and five Terraform tests, plus build and smoke checks; baseline provenance is verified, historical guidance unverified. Added tests cover configuration, rejection, deletion freeing capacity, full-form blocking, and Terraform wiring, but omit concurrent submissions and frontend capacity transitions. Changes remain focused on configuration, enforcement, presentation, and relevant tests, with no added dependencies or weakened validation. The candidate anticipated process-local creation races; review additionally finds that a filter refresh can re-enable submission during an outstanding save, allowing duplicate requests. Discovery of the pre-existing stale-summary race is unestablished; it remains unfixed, while the new capacity update correctly follows the revision guard.

## sonnet

The requested feature works for ordinary sequential use across all three layers, with concurrency and frontend submission-state limitations. Saved validation passes 39 backend, 20 frontend and seven Terraform tests; source review supports global-count enforcement, deletion recovery and unlimited defaults. Added tests cover boundaries, configuration and wiring, but omit concurrent creation, stale capacity, filtered totals and integrated frontend recovery after deletion. Changes remain focused without weakened checks; the baseline is historically verified, while current guidance has unverified historical provenance. Review identifies non-atomic backend enforcement and availability refreshes potentially enabling duplicate submissions during an outstanding save; neither limitation is documented by the candidate. Discovery of the pre-existing stale-summary race is unestablished; it remains unfixed, although the new capacity update correctly follows the revision guard.
