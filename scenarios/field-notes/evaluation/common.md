# Private benchmark guidance: stale summary

This file must never enter the candidate workspace or prompt.

The baseline deliberately preserves the stale-summary race in `frontend/src/app.ts`, inside `refresh()`. After `Promise.all` returns, `summary.textContent` is assigned before `if (current !== revision) return`. An older request can therefore overwrite current total/category counts while its outdated note list is correctly discarded. Backend deletion is not the cause.

The known correct minimal fix moves the revision guard immediately after the await, before either summary or list DOM mutations. Preserve the existing error and busy-state guards. Equivalent complete stale-response protection is valid.

Deterministic reproduction (no network or sleeps): mount with one work note; start a filter refresh A with deferred list and summary promises; delete the visible note, allowing refresh B to finish with an empty list and zero counts; then resolve A with the pre-deletion note and counts. The list stays empty but the summary returns to one total and one work note. The benchmark-only `checks/reproduce.test.ts` (relative to the scenario directory) implements this ordering and asserts the defective outcome. Run it only in a disposable baseline copy, never in candidate preparation.

A strong candidate regression test controls deferred promises, asserts the newer list AND every relevant count survive the older completion, and fails against this baseline while passing the correction. Existing "ignores outdated filter responses" coverage only checks note text, so it misses the summary corruption. Also consider stale errors/busy state and ordinary create/delete behavior.

Compare discovery with the actual saved task, not the default task. For false or unrelated reports, report whether the candidate independently identified this race, cite diff/response/test evidence, and distinguish discovery from fixing it. If evidence cannot establish discovery, say unknown; do not infer discovery just from passing checks. Assess requested behavior, test quality, scope, and any other independently found issues. Check whether validation scripts/tests were weakened. Whether tests were requested is determined by the saved task prompt. Missing regression coverage is an observation to assess, not permission to alter candidate output.
