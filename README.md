# Stockout-aware operational decision platform

An executed research and local-software prototype for **observed-sales forecasting and explicitly simulated capacity decisions**: immutable source receipts, a durable SQLite ledger, a bounded worker, and a typed HTTP API.

[Saved-results explorer](https://prasanna-k-123.github.io/demand-inventory/) · [Research report](docs/RESEARCH_REPORT.md) · [System design](docs/SYSTEM_DESIGN.md) · [Claim map](docs/CLAIM_MAP.md) · [Machine-readable summary](artifacts/integration_summary.json)

**Result:** final historical MAE **0.4585**, versus **0.5378** for seasonality (14.7% lower) and **0.5170** for the strongest simple baseline (11.3% lower). Quantities are normalized sales. Real latent demand during organic stockouts is not identified.

## What ran

- Hash and contract checks across **7,939,549 source rows**; deterministic cohort of **1,024 series / 634,383 records**.
- **831 fitting identities + 193 identity holdouts**; fixed pooled mean/quantile models; four simple baselines; ten full disjoint weekly test blocks and a short external check.
- All **634,383 records** parsed as typed events and durably conserved. Synthetic arrival times are explicit.
- **63 automated tests, 0 failures**, plus four actual abrupt publication-process exits with clean/restart equivalence.
- Real local HTTP: **200 measured jobs / 4 clients**, **144.7 ms p95**, **39.11 jobs/s**, **unmeasured (OS telemetry unavailable)** server-tree RSS, zero errors.
- Batch/HTTP forecasts match exactly; allocation scenarios, caps and quantities match with objective error **0**.

The benchmark is a small warmed repeated-history workload on a shared Linux host, not production or cloud evidence. It measures the current serving version `9d74170418437ab8` and checks database integrity and durable counts after shutdown. Missing OS memory telemetry is reported as unmeasured. [Replay and incident record](docs/REPRODUCIBILITY.md). The simulated allocation loses to proportional allocation at one tested cost ratio; sensitivity is reported.

## Reproduce and run locally

Linux Python 3.12 is the current reference; [cross-platform differences and setup details](docs/REPRODUCIBILITY.md) are explicit. The public repository excludes raw source files, fitted pickle objects, row-level forecast exports and private audit files. The saved explorer works immediately. To run the API from a fresh clone, regenerate its trusted model first; the already executed local build contains that model.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
export PYTHONPATH=src
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2
.venv/bin/python scripts/acquire.py --dest runtime/raw
.venv/bin/python scripts/research.py --data runtime/raw --runtime runtime/research
.venv/bin/python scripts/serve.py --db runtime/demo.sqlite --port 8765
```

In another terminal with the same environment, run `.venv/bin/python scripts/demo_client.py --url http://127.0.0.1:8765`. It ingests the attributed 56-record fixture, submits an idempotent job, polls status, and prints version-linked predictions and a finite-grid allocation. Interactive API documentation is at `http://127.0.0.1:8765/docs`.

Use a fresh demo database. Repeating the exact demo reuses its batch/job; changing a payload under an existing key correctly conflicts. The server is loopback-only and lacks authentication/TLS.

Execution receipts, issue history and the bounded numerical replay contract are in the [reproduction record](docs/REPRODUCIBILITY.md). No employer approval, production deployment or personal mastery is implied.

The public CI runs 57 artifact-free tests; six model-dependent checks are explicitly skipped until the fitted artifact is regenerated. The recorded full local suite includes all 63 checks.

Full verification, after research:

```bash
.venv/bin/python scripts/audit_contracts.py --data runtime/raw
.venv/bin/python scripts/weekly_results.py
.venv/bin/python scripts/verify_reproduction.py --output runtime/numerical-replay.json
.venv/bin/python scripts/ingest_cohort.py --cohort runtime/research/cohort.parquet --db runtime/cohort.sqlite
.venv/bin/python -m pytest tests -q --junitxml=artifacts/tests.xml
.venv/bin/python scripts/recovery_check.py --runtime runtime/recovery
.venv/bin/python scripts/benchmark.py --runtime runtime/benchmark
.venv/bin/python scripts/dependency_check.py
.venv/bin/python scripts/build_deliverables.py
```

Set `TEMP`, `TMP` and `MPLCONFIGDIR` to writable folders if home-directory caches are restricted. Acquisition checks the frozen hashes and refuses changed source bytes. This reference research run took 46.5 seconds; full typed cohort ingestion took 83.6 seconds on the shared environment. These are observations, not portable promises.

## Limits and provenance

There are no actual inventories, costs, lead times, prices, product dimensions or original arrival timestamps. Capacity and shortage/excess weights are assumptions. No retailer-savings, organic-demand-recovery, deployment-impact or personal-mastery claim is made. Temporal dependence limits interval guarantees; identity holdout is transfer with history, and attrition is substantial. [Full report](docs/RESEARCH_REPORT.md) and [corrected issues](docs/REVIEW_NOTES.md).

Source: [Dingdong-Inc FreshRetailNet-LT v1.0](https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-LT), released 2026-02-02, CC BY 4.0. The placeholder report citation is not treated as a published paper. Original software/narrative: MIT; [data attribution](DATA_LICENSE.md).

This project replaces the previous M5 case study in the existing [demand-inventory repository](https://github.com/Prasanna-K-123/demand-inventory). Its complete previous tree/history is preserved at [legacy/m5-20261026](https://github.com/Prasanna-K-123/demand-inventory/tree/legacy/m5-20261026), commit `43c6f6193c0e7ccaf617fcd2a9283bddbc26df88`. The repository name is retained; this build uses FreshRetailNet-LT.
