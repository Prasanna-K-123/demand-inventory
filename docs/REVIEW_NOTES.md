# Review notes and issue history

Research, ingestion, tests, actual crash trials and local HTTP benchmark executed. The dated replay and storage incident record is in [REPRODUCIBILITY.md](REPRODUCIBILITY.md). Independent technical review scope and closed findings are recorded in artifacts/review_status.json; historical review is retained separately in that receipt. This is not employer validation. No browser interaction or visual-browser QA occurred; the explorer has static/content checks only.

## first full-source audit

Observed: DuckDB 2.0 rejects deprecated single-arrow list lambda syntax

Resolution: Use explicit lambda x: expression; pinned actual DuckDB 2.0.0. No source or outcome changes.

## matplotlib import

Observed: Default user-home cache directory denied

Resolution: Set MPLCONFIGDIR to writable runtime cache; first attempt used workspace temporary cache. No plot output yet.

## child HTTP tests

Observed: Windows asyncio socketpair blocked before app startup by child network permissions; TestClient hung. Faulthandler identified socket.accept during event-loop construction.

Resolution: Interrupted both hung test runs. Root execution with existing network permission requested; non-HTTP tests continue. No HTTP pass or latency claim until execution.

## internal design review

Observed: Monitoring originally counted repeated jobs for the same series/date as multiple labels.

Resolution: Deduplicate series/date forecasts before computing label counts; added a regression test that 35 repeated forecasts produce one available label.

## first HTTP memory benchmark

Observed: RSS sampler tracked the Windows virtual-environment launcher (4.2 MiB) and omitted its Python child; initial memory SLO claim invalid.

Resolution: Retain original receipt marked invalid; sample aggregate server process tree and explicitly terminate owned server descendants; rerun actual HTTP benchmark.

## scientific reporting review

Observed: Retrospective validation CQR coverage used later Mar–Apr calibration, so it was not available as-of Jan–Feb. Point-model selection was unaffected.

Resolution: Suppress calibrated validation coverage/width; retain raw quantile losses, and label calibration coverage as in-sample diagnostic. Final and external scores unchanged.

## capacity protocol interpretation

Observed: Protocol named middle scenario q50, while implementation uses the selected point forecast (Poisson mean model).

Resolution: Record an explicit protocol deviation; label all allocation results as equal-weight q10/selected-point/q90 scenarios. No claim that point is a fitted median. No outcome-driven model tuning.

## root integration review

Observed: Initial service allocation used calibrated interval endpoints, while the locked research decision study used raw quantile estimates. Forecast parity did not establish decision-policy parity.

Resolution: Service aligned to frozen raw-quantile/selected-point/raw-quantile scenarios and q90-based caps; added policy ID and explicit scenario matrix, typed allocation result and offline-versus-HTTP allocation checks. Prior response and benchmark retained in artifacts/audit. No research refits or numeric changes.

## root replay review

Observed: Event snapshots alone did not freeze monitoring state: later forecast publications could change fallback policy between attempts.

Resolution: Freeze the complete monitoring summary inside the job submission transaction, filtered to requested model and feature versions. Compute and recovery consume that immutable JSON. Regression publishes 30 threshold-changing historical forecasts between attempts and verifies unchanged output.

## root version-identity review

Observed: Initial model_version was derived from pickle bytes only and did not identify calibration, selected point model or feature implementation.

Resolution: Bind served identity to pickle digest, inference configuration, feature list and hashes of relevant serving implementation files; reject manifest-only or runtime-implementation changes. Preserve old manifest, fitted artifact and receipts; no refit.

## independent review: expired failure publication

Observed: An expired worker could mark a running job failed when its token had not yet been replaced, preventing lease recovery. Successful publication already checked expiry.

Resolution: Failure publication now requires an unexpired lease in addition to current owner/token. Regression proves expired failure does nothing, replacement can reclaim, and current-owner failure succeeds. Rebound version without refitting; prior 200-job performance receipt retained with its version, then current-version HTTP correctness smoke.

Original invalid memory measurements, initial CQR-policy responses and the original retrospective interval export are retained in the local build audit directory. Public distribution excludes fitted pickle objects, row-level forecasts and private audit files. Aggregate corrected results and this issue history are public. Reporting corrections do not retune the model. The Linux replay changes numerical outputs relative to historical Windows values; source/cohort identities, model selection and the reported direction of decision comparisons are preserved. The difference is explicitly quantified in the reproduction record.
