# Inventory input contracts — 22 October 2026

The public API now rejects malformed inputs before they can look like valid
forecasts or operating results. These checks supplement the original frozen
research; they do not change its models, decision rule or measured results.

## Corrected failure cases

- `sba_path([1, NaN, 1])` previously treated the missing period like an ordinary
  no-sale period. Sales history must now be real, finite and nonnegative, with
  a finite scalar smoothing parameter strictly between zero and one.
- Zero, negative and fractional `lead_weeks` previously scheduled orders that
  could never arrive. Delivery delay must now be a positive integer. The model
  supports one or more complete weekly periods; same-period delivery is outside
  this simulator's event order.
- Simulation origins must be consecutive seven-day periods with enough observed
  history and outcome days. Sales/prices, four ordered forecast quantiles and
  unique series identifiers must align. Scenario parameters must be finite and
  nonnegative, and the censoring-proxy switch must be boolean.
- Target windows cannot wrap around a negative index or silently truncate.
  Allocation vectors must align. Missing prices/costs remain allowed as NaN;
  those series receive no new orders. A known orderable cost requires a finite
  shortage penalty.

## Verification and research integrity

All 19 tests pass: the original nine scientific tests and ten regression tests.
The regressions include 80 deterministic complete simulations with different
series counts, budgets, delays, penalties, missing prices and censoring settings.
Every valid result exactly matches the preserved original implementation, and
stock conservation is checked separately.

Two clean runs, original and revised, separately prepare the hash-checked public
M5 ZIP and refit the four fixed quantile models. Fitted model bytes, processed
data, development/final forecasts, the original freeze records, development
selection and final analysis are byte-identical. The receipt lists exact hashes,
execution commands and environment versions. This is same-environment
reproduction, not external replication or evidence of observed retailer savings.

The original `core.py`, training script and evaluation script remain in
`reproducibility/`. The original protocol/model freezes are unchanged.
`scripts/source_integrity.py` verifies the preserved originals and accepts only
the exact documented revised sources, contracts and patch. Unrecorded source
changes still fail closed. The later verification-summary label distinguishes
the nine original scientific tests from the separate current test suite; that
summary script does not itself execute unit tests.

[Machine-readable receipt](../reports/input_contract_revision_20261022.json)
· [Readable patch](../reproducibility/input_contract_revision_20261022.patch)
· [Regression tests](../tests/test_input_contracts.py)
