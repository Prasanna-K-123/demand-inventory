# Stockout-aware operational decision platform

An executed research and local-software prototype for **observed-sales forecasting and explicitly simulated capacity decisions**: immutable source receipts, a durable SQLite ledger, a bounded worker, and a typed HTTP API.

[Saved-results explorer](https://prasanna-k-123.github.io/demand-inventory/) · [Research report](docs/RESEARCH_REPORT.md) · [System design](docs/SYSTEM_DESIGN.md) · [Claim map](docs/CLAIM_MAP.md) · [Machine-readable summary](artifacts/integration_summary.json)

**Result:** final historical MAE **0.4587**, versus **0.5378** for seasonality (14.7% lower) and **0.5170** for the strongest simple baseline (11.3% lower). Quantities are normalized sales. Real latent demand during organic stockouts is not identified.

## What ran

- Hash and contract checks across **7,939,549 source rows**; deterministic cohort of **1,024 series / 634,383 records**.
- **831 fitting identities + 193 identity holdouts**; fixed pooled mean/quantile models; four simple baselines; ten full disjoint weekly test blocks and a short external check.
- All **634,383 records** parsed as typed events and durably conserved. Synthetic arrival times are explicit.
- **44 automated tests, 0 failures**, plus four actual abrupt publication-process exits with clean/restart equivalence.
- Real local HTTP: **200 measured jobs / 4 clients**, **457.6 ms p95**, **13.54 jobs/s**, **178.8 MiB** sampled server-tree RSS, zero errors.
- Batch/HTTP forecasts match exactly; allocation scenarios, caps and quantities match with objective error **0**.

The benchmark is a small warmed repeated-history workload on a shared Windows host, not production or cloud evidence. It measures serving version `509b40e9d63ead14`; the final expired-failure fencing repair is version `47ae70b6ffe5eb2d`, verified by a separate HTTP correctness smoke without repeating performance measurement. The simulated allocation loses to proportional allocation at one tested cost ratio; sensitivity is reported.

## Reproduce and run locally

Python 3.12 is tested. The public repository excludes raw source files, fitted pickle objects, row-level forecast exports and private audit files. The saved explorer works immediately. To run the API from a fresh clone, regenerate its trusted model first; the already executed local build contains that model.

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.lock
$env:PYTHONPATH = (Resolve-Path src).Path
$env:OMP_NUM_THREADS = '2'
$env:OPENBLAS_NUM_THREADS = '2'
$env:MKL_NUM_THREADS = '2'
.venv/Scripts/python.exe scripts/acquire.py --dest runtime/raw
.venv/Scripts/python.exe scripts/research.py --data runtime/raw --runtime runtime/research
.venv/Scripts/python.exe scripts/serve.py --db runtime/demo.sqlite --port 8765
```

In another terminal with the same environment, run `.venv/Scripts/python.exe scripts/demo_client.py --url http://127.0.0.1:8765`. It ingests the attributed 56-record fixture, submits an idempotent job, polls status, and prints version-linked predictions and a finite-grid allocation. Interactive API documentation is at `http://127.0.0.1:8765/docs`.

Use a fresh demo database. Repeating the exact demo reuses its batch/job; changing a payload under an existing key correctly conflicts. The server is loopback-only and lacks authentication/TLS.

Independent AI-agent review passed within the [recorded scope](artifacts/review_status.json); no external employer validation or browser QA is claimed.

The public CI runs 38 artifact-free tests; six model-dependent checks are explicitly skipped until the fitted artifact is regenerated. The recorded full local suite includes all 44 checks.

Full verification, after research:

```powershell
.venv/Scripts/python.exe scripts/audit_contracts.py --data runtime/raw
.venv/Scripts/python.exe scripts/weekly_results.py
.venv/Scripts/python.exe scripts/ingest_cohort.py --cohort runtime/research/cohort.parquet --db runtime/cohort.sqlite
.venv/Scripts/python.exe -m pytest tests -q --junitxml=artifacts/tests.xml
.venv/Scripts/python.exe scripts/recovery_check.py --runtime runtime/recovery
.venv/Scripts/python.exe scripts/benchmark.py --runtime runtime/benchmark
.venv/Scripts/python.exe scripts/dependency_check.py
.venv/Scripts/python.exe scripts/build_deliverables.py
```

Set `TEMP`, `TMP` and `MPLCONFIGDIR` to writable folders if home-directory caches are restricted. Acquisition checks the frozen hashes and refuses changed source bytes. The first research run took 96.8 seconds; full typed cohort ingestion took 249.3 seconds on the shared environment. These are observations, not portable promises.

## Limits and provenance

There are no actual inventories, costs, lead times, prices, product dimensions or original arrival timestamps. Capacity and shortage/excess weights are assumptions. No retailer-savings, organic-demand-recovery, deployment-impact or personal-mastery claim is made. Temporal dependence limits interval guarantees; identity holdout is transfer with history, and attrition is substantial. [Full report](docs/RESEARCH_REPORT.md) and [corrected issues](docs/REVIEW_NOTES.md).

Source: [Dingdong-Inc FreshRetailNet-LT v1.0](https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-LT), released 2026-02-02, CC BY 4.0. The placeholder report citation is not treated as a published paper. Original software/narrative: MIT; [data attribution](DATA_LICENSE.md).

This project replaces the previous M5 case study in the existing [demand-inventory repository](https://github.com/Prasanna-K-123/demand-inventory). Its complete previous tree/history is preserved at [legacy/m5-20261026](https://github.com/Prasanna-K-123/demand-inventory/tree/legacy/m5-20261026), commit `43c6f6193c0e7ccaf617fcd2a9283bddbc26df88`. The repository name is retained; this build uses FreshRetailNet-LT.
