# Task evaluation: note-limit

The feature is deliberately underspecified. Accept reasonable, clearly explained engineering choices rather than requiring one implementation or an invented API contract. Assess requested feature completeness separately from independently anticipated edge cases and engineering judgment. The private cases below are not additional requirements disclosed to the candidate: do not turn every unhandled case into an automatic failure or reward unnecessary complexity.

## Requested feature completeness

- Terraform dev configuration, sensible defaults and validation of invalid limits.
- Propagation through module inputs/app settings and backend configuration.
- Backend enforcement for creation, including consistency across persistence modes. Frontend-only enforcement does not satisfy the task.
- API behavior at the limit, useful errors, and continued read/delete access.
- Frontend presentation of the configured limit and prevention of creation when full, including reaching capacity and freeing space.
- Backward-compatible behavior when no explicit limit is configured.
- Agreement on units, values, defaults and semantics across all three layers. Accept reasonable documented choices where the prompt leaves semantics open.

## Independent anticipation and robustness

Use these cases to distinguish a straightforward implementation from one that anticipates real use. For each relevant case, distinguish explicit recognition in the response or tests, handling visible in the implementation, a documented limitation, and an unaddressed or unknown case. Correct behavior alone does not prove that the candidate consciously identified the issue. Explain practical impact rather than treating this as an all-or-nothing checklist. If a case reveals a direct failure of the requested feature, report that failure under feature completeness as well, without double-counting it.

- Global versus filtered counts: does the implementation use the collection total rather than the visible list length? Consider a full collection with zero search results or a category showing only some notes. Filtering should not bypass backend enforcement or misleadingly restore frontend capacity.
- Lowering the limit below the existing count: does the candidate preserve data and read/delete access, block creation at or above the limit, and enable creation only after enough space is freed? For example, with five existing notes and a new limit of three, robust behavior blocks creation at counts five, four and three, and allows it at two. Distinguish a justified configuration policy from accidental equality-only checks or destructive behavior.
- Stale capacity in another browser tab: if another tab has already used the last slot, does backend enforcement still hold? Does the frontend handle rejection with a useful message, preserve entered form values, and recover its capacity state without a page reload? Backend enforcement is required; these additional recovery behaviors distinguish robustness. Do not require live cross-tab synchronization or prescribe a particular HTTP status code.
- Out-of-order responses: can earlier refreshes overwrite newer counts or creation state? Consider both an older full response arriving after deletion frees space and an older spare-capacity response arriving after the collection becomes full. Inspect all relevant state updates, not just the rendered note list.
- Concurrent check-then-create races: does the candidate notice them and accurately explain the practical guarantees across persistence modes? Strict atomic enforcement across multiple backend instances is not an explicit requirement. Credit proportionate safeguards and honest limitations; unsupported claims of atomic enforcement count against engineering judgment.
- Pre-existing stale-summary race: does the candidate independently identify it, and does it fix or test it? The prompt does not disclose this defect or explicitly request response-ordering protection. Report discovery separately from feature completeness; an equivalent protective restructuring is valid but does not alone establish conscious discovery. Do not mistake the existing bug for a newly introduced one or automatically fail the feature solely for leaving it untouched. Explain if the chosen limit UI relies on stale state and consequently fails the requested behavior.

## Tests and evidence

Assess independently added tests for boundaries, invalid configuration, omitted limits, backend rejection, frontend behavior and Terraform wiring, as well as any of the edge cases above. The task does not explicitly request tests; assess their quality and relevance rather than just their number. Distinguish a mentioned concern, an implemented safeguard, and a regression test that actually exercises the failure mode.

Use source, full diff, validation and response as evidence; passing the original suite alone does not prove the new feature works. These cases are review criteria, not evidence that they were executed. Distinguish behavior inferred through source review from demonstrated coverage, and state uncertainty when the saved evidence cannot establish correctness. Favor a focused, coherent implementation with justified tradeoffs over either superficial happy-path code or speculative overengineering.
