# Executed reference and reliability boundaries

The current tables use the **28 October 2026 Linux replay** of the unchanged study protocol. Acquisition checked both original source hashes; all 7,939,549 source rows were audited. The deterministic 1,024-series cohort, fitting identities, time boundaries and model selection are unchanged. No final-outcome tuning or new holdout is claimed.

## Numerical reference

The current reference used CPython 3.12.14 (Clang 22.1.3), NumPy 2.3.5, pandas 2.2.3, scikit-learn 1.8.0 and SciPy 1.17.0, with two numerical threads. Package versions are recorded in [requirements.lock](../requirements.lock). Package pins do not pin every compiler, mathematical library or CPU implementation.

The fresh 28 October fit reproduced the earlier 26 October Linux fitted object byte for byte (`0985c8e73839f783bbf820cc155d09cd81ff848e2e05aac503f84666b6148bd0`), and all 120 previously recorded numerical comparison fields matched exactly. The model object is generated locally and is not distributed. Changing the serving ledger changes its bound configuration version without refitting the statistical models.

The historical Windows build remains available at [commit 7d6df8f](https://github.com/Prasanna-K-123/demand-inventory/tree/7d6df8fb62ca9db23d8d637cb28a675f4ae9c0df). These results are **not cross-platform byte-identical**:

| Quantity | Historical Windows | Linux reference |
|---|---:|---:|
| Final pooled observed-sales MAE | 0.4587174104 | 0.4585390937 |
| Final nominal-80% interval coverage | 0.8036157788 | 0.8045107735 |
| Daily-average paired MAE difference versus seasonal | -0.0800339656 | -0.0802104947 |
| Scenario proxy cost, shortage weight 3 | 15.2749594595 | 15.2409054054 |
| Proportional proxy cost, shortage weight 3 | 15.3644729730 | 15.2942027027 |

The [complete aggregate comparison](../artifacts/platform_comparison.json) preserves both values, original file hashes and changed fields. Source hashes, logical cohort, simple-baseline results and conditional artificial-masking calculations agree. The pooled model remains the validation-selected candidate; its final MAE remains below each simple baseline. The scenario rule still loses at shortage weight 1 and has lower proxy cost at weights 3 and 5. These are conclusions about the declared historical experiment, not guarantees about operational decisions.

### Why tiny arithmetic changes can matter

A controlled refit on identical saved features with one thread instead of two reproduced all three fitted tree arrays and final predictions exactly. A second controlled calculation replaced only vectorized `log1p`, sine and cosine with mathematically equivalent scalar functions. The largest feature change was `4.44e-16`, but 1,246 histogram-bin assignments changed. That changed fitted trees and some individual predictions materially. The [precision-sensitivity receipt](../artifacts/precision_sensitivity.json) reports the actual changes.

This demonstrates a mechanism for sensitivity in histogram boosting. It does **not identify the exact operation responsible for the original Windows difference**, because its fitted object and feature matrices were not available for direct inspection. The historical difference is not relabelled harmless floating-point roundoff.

The numerical verification script requires exact identities, counts, types and decisions, with only a `1e-12` absolute/relative budget for floating-point reductions. That budget is far below the observed platform model differences; those differences fail rather than pass through a widened tolerance. Other environments must investigate a failed comparison and record a new version if appropriate.

## Reproduction commands

Use the Linux environment and dependency installation shown in the README. Raw data, fitted objects, row-level exports, runtime databases and logs stay local.

```bash
export PYTHONPATH=src
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2
.venv/bin/python scripts/acquire.py --dest runtime/raw
.venv/bin/python scripts/research.py --data runtime/raw --runtime runtime/research
.venv/bin/python scripts/weekly_results.py
.venv/bin/python scripts/verify_reproduction.py --output runtime/numerical-replay.json
.venv/bin/python -m pytest tests -q
.venv/bin/python scripts/recovery_check.py --runtime runtime/recovery
.venv/bin/python scripts/benchmark.py --runtime runtime/benchmark
.venv/bin/python scripts/ingest_cohort.py --cohort runtime/research/cohort.parquet --db runtime/cohort.sqlite
```

Use a new database path for a fresh ingestion measurement. Replaying an existing batch is idempotent and is not a fresh throughput observation. Optional precision investigation, after research:

```bash
.venv/bin/python scripts/precision_probe.py --features runtime/research/features.parquet --output runtime/precision-probe.json
```

## Storage incident and tested mitigation

Two actual HTTP tests using transient connections and SQLite WAL returned `database disk image is malformed`. The saved database headers described more pages than the files physically contained. The initiating cause has not been established. A separate small file-copy experiment reproduced older-timestamp file reversion in the execution environment, but it does not prove what corrupted the databases.

The current bounded local service explicitly uses **SQLite DELETE rollback journaling with FULL synchronization**, verified at initialization. This preserves transaction, snapshot, idempotency and lease-fencing semantics while avoiding the observed WAL connection/checkpoint configuration. It is a tested mitigation, not a claim that SQLite WAL is generally unsafe or that the original cause is solved.

Three final runs each completed 200 measured HTTP jobs after 20 warm-ups with four clients and one worker. Every run passed post-shutdown `integrity_check`, foreign-key checks and exact durable counts: 221 jobs/results and 222 feature/forecast rows, including the final two-series request. All four abrupt process-exit cases retained clean/restart semantic equivalence. The full 634,383-row typed ingestion passed conservation, replay and integrity checks. [Repeated-load receipt](../artifacts/reliability_replay.json) · [latest benchmark](../artifacts/benchmark.json) · [recovery](../artifacts/recovery_receipt.json) · [ingestion](../artifacts/ledger_ingestion_receipt.json).

Connection setup now lies inside the cleanup boundary, so a PRAGMA failure closes the opened connection. Tests exercise those failures. Successful benchmark output is written only after durable-state and unchanged model/manifest checks. Missing OS memory access produces `null` RSS and an unverified memory threshold, not a zero-memory claim.

In DELETE mode, FULL synchronization does not establish power-loss durability of the last committed transaction; SQLite documents that EXTRA also syncs the journal directory. Power-loss testing is outside this prototype contract. See [SQLite synchronous semantics](https://www.sqlite.org/pragma.html#pragma_synchronous).

These checks cover a small warmed local workload. They do not certify filesystem behavior, power-loss recovery, cloud deployment, sustained traffic, production backups or multihost operation. Keep database/journal files together; never copy or replace a live database outside SQLite's supported backup mechanisms. See the primary SQLite documentation on [journaling](https://sqlite.org/wal.html) and [corruption causes and backup safety](https://sqlite.org/howtocorrupt.html).
