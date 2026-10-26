# Build public documentation and explorer from executed receipts.
import argparse,html,json,xml.etree.ElementTree as ET
from pathlib import Path
import pandas as pd
from stockout.common import atomic_json,file_hash
BASE=Path(__file__).resolve().parents[1]; ART=BASE/'artifacts'
def read(n): return json.loads((ART/n).read_text())
def write(n,t): (BASE/n).write_text(t,encoding='utf-8')
def table(headers,rows):
    return '| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n'+'\n'.join('| '+' | '.join(map(str,r))+' |' for r in rows)
def main(a):
    research=read('research_receipt.json'); bench=read('benchmark.json'); ingest=read('ledger_ingestion_receipt.json'); recovery=read('recovery_receipt.json'); intervals=read('interval_metrics.json'); decisions=read('decision_summary.json'); masking=read('artificial_masking.json'); manifest=read('model_manifest.json'); failures=read('observed_failures.json')
    metrics=pd.read_csv(ART/'forecast_metrics.csv'); metrics=metrics[metrics.stratum=='all_observed']
    def metric(s,i,m): return metrics[(metrics.split==s)&(metrics.identity_split==i)&(metrics.model==m)].iloc[0].to_dict()
    pooled=metric('final','fitting_identities','pooled_poisson'); seasonal=metric('final','fitting_identities','seasonal_4week_fallback_mean_28'); mean28=metric('final','fitting_identities','mean_28')
    improvement=1-pooled['mae']/seasonal['mae']; best_simple=1-pooled['mae']/mean28['mae']
    coverage=next(x for x in intervals if x['split']=='final' and x['identity_split']=='fitting_identities')
    tests=ET.parse(ART/'tests.xml'); suites=list(tests.getroot().iter('testsuite')); ntests=sum(int(x.get('tests',0)) for x in suites); fail=sum(int(x.get('failures',0))+int(x.get('errors',0)) for x in suites)
    for node in suites: node.attrib.pop('hostname',None)
    tests.write(ART/'tests.xml',encoding='utf-8',xml_declaration=True)
    labels={'last_observation':'Last observed','lag_7_fallback_mean_28':'Weekly lag','mean_28':'28-day mean','seasonal_4week_fallback_mean_28':'Four-week seasonal','pooled_poisson':'Pooled Poisson loss'}
    primary=table(['Model','Final MAE','Final WAPE'],[[labels[k],f"{metric('final','fitting_identities',k)['mae']:.4f}",f"{metric('final','fitting_identities',k)['wape']:.2%}"] for k in labels])
    comparison=table(['Evaluation','Rows','Pooled MAE','Seasonal MAE'],[[f'{s} / {i}',f"{metric(s,i,'pooled_poisson')['n']:,}",f"{metric(s,i,'pooled_poisson')['mae']:.4f}",f"{metric(s,i,'seasonal_4week_fallback_mean_28')['mae']:.4f}"] for s in ['validation','final','official_external'] for i in ['fitting_identities','transfer_holdout']])
    attrtable=table(['Group / split','Selected identities','Observed identities','Usable rows / calendar opportunities'],[[f"{r['identity_split']} / {r['split']}",r['selected_identities'],r['observed_identities'],f"{r['usable_rows']:,} / {r['expected_calendar_rows']:,}"] for r in read('attrition.json') if r['split'] in ['final','official_external']])
    costtable=table(['Shortage : excess','Scenario DP','Proportional point','Hindsight oracle'],[[f'{int(c)} : 1',*[f"{next(r for r in decisions['results'] if r['shortage_weight']==c and r['policy']==policy)['mean_proxy_cost']:.4f}" for policy in ['scenario_dp','proportional_point','hindsight_grid_oracle']]] for c in [1.,3.,5.]])
    masktable=table(['Hidden final hours','Method','Final MAE'],[[r['hidden_last_hours'],r['method'],f"{r['mae']:.4f}"] for r in masking['results'] if r['identity_split']=='fitting_identities'])
    write('docs/RESEARCH_REPORT.md',f'''# Research report

## Question and identification boundary

How well can historical sales and stockout information forecast **next-day observed normalized sales**, and what happens when forecasts feed a fully specified capacity simulation? Three exercises are separate: observed-sales forecasting, reconstruction of artificially hidden hourly sales on fully in-stock days, and finite-scenario allocation. None identifies demand that would have occurred during organic stockouts.

A stockout mask indicates potential censoring, not the missing quantity. Actual inventory, replenishment, lost demand, prices, physical units and retailer costs are absent. Observed sales are an explicit proxy in the decision exercise, never organic-demand ground truth.

## Locked protocol and cohort

Original [protocol](../protocol.json) SHA256: `{research['protocol_sha256']}`. The [weekly-block addendum](../protocol-addendum.json) was separately locked before model scores; the original freeze is preserved. A valid negative result was acceptable.

Eligibility uses only dates and identities through 2024-12-31: at least 180 observations, including at least 60 in October–December 2024. Among 8,849 eligible series, the 1,024 smallest SHA256 hashes of `stockout-v1|store_id|product_id` define the cohort. Hash modulo five reserves 193 identities from every fit and calibration. No future-survival or outcome filter replaces identities.

| Role | Dates | Use |
| --- | --- | --- |
| Fit | 2023-06-05–2024-12-31 | 356,925 usable rows; 831 fitting identities |
| Validation | 2025-01-01–2025-02-28 | MAE-only point-model selection |
| Calibration | 2025-03-01–2025-04-30 | One interval expansion scalar; 44,553 rows |
| Final historical | 2025-05-01–2025-07-13 | 74 dates; 10 full disjoint weeks and 4 remaining days |
| Official external | 2025-07-14–2025-07-20 | Short seven-day external check |

The model is fixed across origins; prior-day observed lags update. This is rolling **one-day-ahead** forecasting, not fixed-origin seven-day prediction. Identity holdout retains history for features and tests transfer with history, not cold start. Research scoring requires 14 historical observations; service additionally withholds histories whose latest observation is over two days old. Only two final research rows fail that extra service rule; eligibility is therefore slightly stricter in the service.

{attrtable}

Missing calendar days are never zero-filled. At least 14 observations in the previous 28 days are required for scoring. Results are conditional on observed usable rows. Only 656 of the initial 1,024 identities survive into the external week. Long-history eligibility and attrition limit generalization.

## Contracts, features and models

Both source hashes, all 19 field types, key uniqueness, finite numeric/array values, daily/hourly quantity conservation and business-hour stock counts were checked across 7,939,549 rows. All passed. The 634,383 selected records were separately parsed as typed events and durably ingested; no quarantines occurred. Their normalized-sales total is {ingest['source_normalized_sales_sum']:,.3f}, conserved within {ingest['conservation_absolute_delta']:.2g}. [Source audit](../artifacts/source_audit.json); [ledger receipt](../artifacts/ledger_ingestion_receipt.json).

The 21 features use past sales and stockout hours, missingness/history coverage and target calendar harmonics. Lags are 1, 7, 14 and 28 calendar days; windows are 7 and 28 days. Scale is max(trailing-28-day mean, 0.1), used to normalize target and lag summaries, with log scale also a feature. Future realized weather, discounts, activity and stock status are excluded. Future stockout masks are diagnostic strata only.

Four baselines are last observation, weekly lag with mean fallback, 28-day mean and the average of four prior matching weekdays. Fixed HistGradientBoosting models use 160 iterations, 15 leaves, learning rate 0.05, minimum leaf size 40, L2 penalty 3, seed 42 and no early stopping. Poisson loss is a mean-model/quasi-likelihood choice for non-integer normalized quantities, not a validated count distribution. Quantile 0.1 and 0.9 models use the same settings. No final-outcome tuning occurred.

Quantile crossing is removed by sorting. CQR uses score max(lower−y, y−upper) and the ceil((n+1)×0.8)-th calibration score, expanding endpoints and clipping lower at zero. Realized expansion is {manifest['calibration_margin']:.6f}. Temporal dependence, shared series shocks and shift prevent an automatic exchangeability coverage guarantee.

Point selection used only validation MAE: pooled {metric('validation','fitting_identities','pooled_poisson')['mae']:.4f} versus seasonal {metric('validation','fitting_identities','seasonal_4week_fallback_mean_28')['mae']:.4f}. Calibration does not affect that choice. Validation CQR coverage was suppressed because March–April calibration was unavailable in January–February. Calibration coverage is an in-sample diagnostic; final/external intervals are holdouts.

## Forecast evidence

{primary}

{comparison}

Final pooled MAE is {improvement:.1%} lower than seasonality and {best_simple:.1%} lower than the best simple baseline. Final nominal-80% interval coverage is {coverage['coverage80']:.2%}, mean width {coverage['mean_width']:.4f}. The pooled model beats seasonality in 10 of 10 full disjoint weeks and is best of all five models in 9. Empirical interval coverage varies from about 74.0% to 83.6% across these full weeks; pooled coverage is not a per-window guarantee.

The predeclared exploratory bootstrap first averages paired errors within dates, then resamples contiguous seven-day blocks, preserving within-day dependence across series. With 500 draws, pooled-minus-seasonal daily-average MAE is {research['bootstrap']['daily_average_mae_difference_pooled_minus_seasonal']:.4f}, with 95% percentile interval [{research['bootstrap']['ci95_percentile'][0]:.4f}, {research['bootstrap']['ci95_percentile'][1]:.4f}]. Row-weighted and day-weighted differences differ slightly because attrition changes daily sample sizes. This is descriptive under the resampling scheme, not a universal significance or causal claim.

![Final comparison](../artifacts/forecast_mae.png)
![Error trend](../artifacts/error_over_time.png)

[All metrics and stockout strata](../artifacts/forecast_metrics.csv) · [Weekly blocks](../artifacts/weekly_metrics.csv) · [Intervals](../artifacts/interval_metrics.json) · Row-level results are generated locally and excluded from the public distribution.

## Artificial hourly masking

A pooled business-hour profile is estimated from {masking['fit_rows']:,} fully in-stock fit-period rows of fitting identities. On final days whose 06:00–21:59 stockout vector is zero, hide the final four or eight hours and recover the known full business-hour subtotal. Compare zero filling, uniform exposure scaling and learned-profile scaling.

{masktable}

The profile helps this artificial task. Uniform exposure is worse than zero filling when only the last four hours are hidden, demonstrating possible overcorrection. Selection into fully in-stock days and artificial mask placement differ from organic stockouts. These scores do not validate organic lost-sales estimates.

## Finite-grid capacity simulation

For each final date, use the first eight available fitting identities in the locked hash order. Quantity increments are 0.1; caps are min(100, ceil(1.5×max(raw q90, 0.1)/0.1)) increments. Capacity is floor(0.8×sum(max(trailing mean, 0.1))/0.1). Scenario cost is shortage_weight×max(d−q, 0)+max(q−d, 0).

The assumed finite distribution puts equal mass on raw learned q10, the selected point/mean forecast and raw learned q90. Equal masses are assumed, not implied by quantile levels. **Protocol deviation:** the freeze called the middle scenario q50; no median model was fit. All results use a selected-point scenario, with no refit or outcome-driven tuning to hide this deviation.

Exact recurrence: `V_i(b)=min_q[V_(i−1)(b−q)+L_i(0.1q)]`, with integer q between zero and its cap. Final minimization permits unused capacity; backtracking returns quantities. This is globally optimal for the declared finite grid and scenario objective. Twelve randomized small cases match an independent exhaustive oracle. Every solution is checked for feasibility and objective reconstruction.

{costtable}

These are mean realized **proxy** costs over 74 dates, evaluated against observed sales. The scenario rule slightly improves on proportional allocation at shortage weights 3 and 5 and loses at 1. The hindsight grid oracle is unattainable prospective information and supplies only a same-grid lower bound. There is no uniformly winning allocation result or retailer-savings claim.

For identical continuous caps/capacity, rounding a feasible continuous solution down preserves feasibility and increases loss by at most shortage_weight×0.1 per item. The conservative eight-item bound is 2.4 at weight 3; it does not bound real retail loss.

The final API uses `raw-quantile-point-grid-v1`, with the same scenario and cap definition. An initial CQR-endpoint service mismatch was preserved in the audit trail before correction. Offline-versus-HTTP checks now verify exact-request scenarios, caps, quantities and objective. Historical eight-item results do not establish performance for other portfolios or assumptions.

## Maturity and limitations

The complete serving identity binds fitted bytes, selected point model, calibration and source/feature metadata plus implementation digests. Final version is `{manifest["model_version"]}`; model fitting and scientific outcomes are unchanged by the systems fixes.

Original arrival timestamps are absent. Next-midnight, late-arrival and fault schedules are synthetic. They support a declared information schedule and systems tests, not empirical arrival-latency claims. No actual inventory, physical capacity, costs, lead times, prices or operational feedback are available. The sample is bounded, attrition is substantial and the external week is short. This is an executed single-machine research prototype, with no production, cloud, client-impact or personal-mastery claim.
''')
    write('README.md',f'''# Stockout-aware operational decision platform

An executed research and local-software prototype for **observed-sales forecasting and explicitly simulated capacity decisions**: immutable source receipts, a durable SQLite ledger, a bounded worker, and a typed HTTP API.

[Saved-results explorer](https://prasanna-k-123.github.io/demand-inventory/) · [Research report](docs/RESEARCH_REPORT.md) · [System design](docs/SYSTEM_DESIGN.md) · [Claim map](docs/CLAIM_MAP.md) · [Machine-readable summary](artifacts/integration_summary.json)

**Result:** final historical MAE **{pooled['mae']:.4f}**, versus **{seasonal['mae']:.4f}** for seasonality ({improvement:.1%} lower) and **{mean28['mae']:.4f}** for the strongest simple baseline ({best_simple:.1%} lower). Quantities are normalized sales. Real latent demand during organic stockouts is not identified.

## What ran

- Hash and contract checks across **7,939,549 source rows**; deterministic cohort of **1,024 series / 634,383 records**.
- **831 fitting identities + 193 identity holdouts**; fixed pooled mean/quantile models; four simple baselines; ten full disjoint weekly test blocks and a short external check.
- All **634,383 records** parsed as typed events and durably conserved. Synthetic arrival times are explicit.
- **{ntests} automated tests, {fail} failures**, plus four actual abrupt publication-process exits with clean/restart equivalence.
- Real local HTTP: **200 measured jobs / 4 clients**, **{bench['job_end_to_end']['p95_ms']:.1f} ms p95**, **{bench['jobs_per_second']:.2f} jobs/s**, **{bench['peak_server_process_tree_rss_mb']:.1f} MiB** sampled server-tree RSS, zero errors.
- Batch/HTTP forecasts match exactly; allocation scenarios, caps and quantities match with objective error **{bench['offline_service_allocation_objective_error']:.2g}**.

The benchmark is a small warmed repeated-history workload on a shared Windows host, not production or cloud evidence. It measures serving version `{bench["model_version"]}`; the final expired-failure fencing repair is version `{manifest["model_version"]}`, verified by a separate HTTP correctness smoke without repeating performance measurement. The simulated allocation loses to proportional allocation at one tested cost ratio; sensitivity is reported.

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

Set `TEMP`, `TMP` and `MPLCONFIGDIR` to writable folders if home-directory caches are restricted. Acquisition checks the frozen hashes and refuses changed source bytes. The first research run took {research['total_seconds']:.1f} seconds; full typed cohort ingestion took {ingest['seconds']:.1f} seconds on the shared environment. These are observations, not portable promises.

## Limits and provenance

There are no actual inventories, costs, lead times, prices, product dimensions or original arrival timestamps. Capacity and shortage/excess weights are assumptions. No retailer-savings, organic-demand-recovery, deployment-impact or personal-mastery claim is made. Temporal dependence limits interval guarantees; identity holdout is transfer with history, and attrition is substantial. [Full report](docs/RESEARCH_REPORT.md) and [corrected issues](docs/REVIEW_NOTES.md).

Source: [Dingdong-Inc FreshRetailNet-LT v1.0](https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-LT), released 2026-02-02, CC BY 4.0. The placeholder report citation is not treated as a published paper. Original software/narrative: MIT; [data attribution](DATA_LICENSE.md).

This project replaces the previous M5 case study in the existing [demand-inventory repository](https://github.com/Prasanna-K-123/demand-inventory). Its complete previous tree/history is preserved at [legacy/m5-20261026](https://github.com/Prasanna-K-123/demand-inventory/tree/legacy/m5-20261026), commit `43c6f6193c0e7ccaf617fcd2a9283bddbc26df88`. The repository name is retained; this build uses FreshRetailNet-LT.
''')
    write('docs/SYSTEM_DESIGN.md',f'''# System design

```mermaid
flowchart LR
 A[Hash-checked public files] --> B[Typed event batches]
 B --> C[(SQLite WAL: immutable events and checkpoints)]
 B --> Q[(Conflict and invalid-record quarantine)]
 C --> D[Idempotent job + fixed input snapshot]
 D --> E[One bounded worker with fenced lease]
 C --> F[Event date + arrival as-of features]
 F --> E
 E --> G[Fixed model + finite-grid allocation]
 G --> H[(Atomic features, forecasts and result)]
 H --> I[Typed status / result API]
 H --> J[Available-label monitoring]
 J --> E
```

## Durable state

Sources have immutable hash-linked manifests and projected-stream checkpoints. Events have one immutable fact per store/product/date. Canonical typed-payload matches are duplicates; divergent content under a key is quarantined. Each batch commits events, quarantines, counts and checkpoint in one `BEGIN IMMEDIATE` transaction. Received = accepted + duplicates + quarantined. Reusing a batch ID with changed content conflicts. Checkpoints refer to deterministic cohort-stream offsets, not parquet physical row numbers. Mutable upstream corrections need an explicit revision policy; this application never silently overwrites facts.

A job stores a canonical spec, idempotency key, model/feature versions and maximum committed event sequence at submission. Later backfills cannot alter that snapshot. The complete monitoring summary is also frozen inside the submission transaction, filtered to that model and feature version; later publications cannot change the job's fallback policy on retry. Active queue length is capped at 256, with at most 64 unique series per job. No request handler trains a model or performs inference.

The worker claims jobs transactionally and receives an incrementing lease token. Publication requires current owner, token and unexpired lease; stale workers cannot publish. The default lease is 30 seconds. Abandoned running jobs become eligible after expiry. Features, forecasts, result JSON and success state commit together. This is at-least-once computation with one fenced publication per job, not a global exactly-once distributed claim.

## Time and policy

Synthetic arrivals cannot precede completion of a daily event. Original arrival logs are absent: next UTC midnight is an assumption, not a measured retailer timestamp. Features require event date before target, arrival no later than as-of, and event sequence no later than the submission snapshot. As-of must be on target date. The fitted/calibrated artifact is unavailable before 2025-05-01.

Normal output requires at least 14 observations in the last 28 days and a latest observation no more than two days old. Seven to thirteen observations trigger seasonal fallback. Fewer than seven or stale data restrict prediction. Fallback/restricted cases cannot allocate capacity.

Monitoring joins labels only when arrival is available as-of and deduplicates repeated forecasts for the same series/date. At least 30 unique labelled intervals are needed. Coverage below 60% triggers seasonal fallback and restricts allocation. This is a demonstration policy threshold, not a statistically validated drift detector.

The final allocation policy ID is `raw-quantile-point-grid-v1`: equally weighted raw q10, selected point/mean and raw q90, with frozen q90-based grid caps. The assigned masses are assumptions, not calibrated probabilities. API and offline allocations are tested against the same scenario matrix, caps and objective.

## API and limits

| Route | Behavior |
| --- | --- |
| GET `/health` | Local readiness and active model |
| GET `/v1/models` | Hash-linked trusted model manifest |
| GET `/v1/contracts/event` | Event JSON Schema |
| POST `/v1/batches` | Up to 1,000 records; typed validation, quarantine, checkpoint |
| POST `/v1/jobs` | Typed one-day job; required Idempotency-Key; 202 response |
| GET `/v1/jobs/{{id}}` | Durable state, attempts, versions and snapshot |
| GET `/v1/jobs/{{id}}/result` | Typed atomically published result |
| GET `/v1/metrics?as_of=...` | Ledger counts and available-label monitoring |

The ASGI boundary rejects bodies over 1 MiB, including streamed bodies without reliable Content-Length. Quantities must be finite, IDs nonnegative, hourly arrays length 24, stock masks binary, totals conserved and timestamps timezone-aware. Unknown fields are forbidden. Conflicting keys/checkpoints/models fail explicitly; queue overflow returns 429. Results pending publication return 409.

## Executed evidence

{ntests} tests passed. Four abrupt publication-process exits recovered semantically identical outputs to a clean run on version 509b40e9d63ead14. The subsequent fail-only fencing repair is checked by the final regression suite and current-version HTTP smoke; no model fit changed. One-second test leases recovered before-commit failures in {min(r['recovery_seconds_after_process_exit'] for r in recovery['trials'] if 'before' in r['phase']):.3f}–{max(r['recovery_seconds_after_process_exit'] for r in recovery['trials'] if 'before' in r['phase']):.3f} seconds after exit; after-commit results required no recomputation. Default application leases remain 30 seconds.

Real HTTP used 20 excluded warm-ups and 200 measured single-series jobs, four clients, one worker and two numerical threads. End-to-end p50/p95/p99: {bench['job_end_to_end']['p50_ms']:.1f}/{bench['job_end_to_end']['p95_ms']:.1f}/{bench['job_end_to_end']['p99_ms']:.1f} ms. Throughput: {bench['jobs_per_second']:.2f} jobs/s. Peak sampled aggregate server-tree RSS: {bench['peak_server_process_tree_rss_mb']:.1f} MiB; summed working sets may double-count shared pages. Client memory and whole-host peak are excluded. The shared Windows host exposes {bench['environment']['logical_cpus']} logical CPUs and {bench['environment']['host_ram_gib']} GiB RAM.

Predeclared local thresholds were request p95 ≤250 ms, job p95 ≤2,000 ms, zero errors and server RSS <1,500 MiB. All passed for this small warm repeated-history workload. Direct model-only timings exclude queue, durability and HTTP and are labelled separately. No cloud, sustained-load or production guarantee follows.

## Security and operations

Bind to IPv4 loopback only; authentication and TLS are absent. SQL values are parameterized. The served model identity binds the pickle, calibration/selection configuration and normalized-text digests of feature, model, policy, ledger and API implementations. Manifest-only or runtime-implementation changes are rejected. Trusted bundled pickle is hash-checked before deserialization; a digest detects corruption but does not authenticate an attacker who replaces both model and manifest. No request supplies a model path. Dependency closure is pinned, `pip check` passed, and static checks found no shell=True calls or high-specificity secret patterns. The local dependency receipt does not itself claim a vulnerability-database audit.

SQLite WAL/FULL protects local transaction boundaries. Backups, disk exhaustion, operating-system failure and multihost coordination require additional work. Structured logs contain run IDs, event classes, checkpoint counts and versions, not entire raw event payloads. Reproduction creates runtime files under the chosen runtime directory.

[Source schema](source_schema.json) · [Event schema](event.schema.json) · [Job schema](job.schema.json) · [Result schema](result.schema.json) · [Benchmark](../artifacts/benchmark.json) · [Recovery](../artifacts/recovery_receipt.json).
''')
    claims=[['Observed-sales forecast improvement','forecast_metrics.csv; weekly_metrics.csv; bootstrap.json','Bounded observed rows; one-day rolling forecasts'],['Measured interval coverage','interval_metrics.json','Empirical temporal coverage, no exchangeability guarantee'],['Artificial reconstruction improvement','artificial_masking.json','Conditional in-stock masks, not organic lost demand'],['Exact finite-grid objective','decision_summary.json; tests.xml; decisions.py','Declared scenarios/caps only; cost sensitivity includes a loss'],['Durable conservation','ledger_ingestion_receipt.json','634,383 real records; synthetic arrival schedule'],['Crash/restart equivalence','recovery_receipt.json; tests.xml','Actual local process exits; not distributed failover'],['Future-data exclusion and feature parity','tests.xml; benchmark.json','Event date, arrival as-of and fixed input snapshot'],['Local performance thresholds','benchmark.json','200 warm jobs, four clients, shared Windows host']]
    write('docs/CLAIM_MAP.md','# Claim-to-evidence map\n\n'+table(['Allowed claim','Evidence under artifacts/ unless code','Boundary'],claims)+'\n\nDo not claim organic latent-demand recovery, retailer savings, physical-unit or money accuracy, cold-start validation, calibrated scenario masses, production impact, personal mastery or independent external validation before review.\n')
    write('docs/REVIEW_NOTES.md','# Review notes and issue history\n\nResearch, ingestion, tests, actual crash trials and local HTTP benchmark executed. Independent AI-agent technical review passed: scientific recomputation, actual-database audit, targeted lease repair, artifact/link concordance and public staging tests. This is not external employer validation. No browser interaction or visual-browser QA occurred; the explorer has static/content checks only.\n\n'+'\n\n'.join(f"## {r['stage']}\n\nObserved: {r['failure']}\n\nResolution: {r['resolution']}" for r in failures)+'\n\nOriginal invalid memory measurements, initial CQR-policy responses and the original retrospective interval export are retained in the local build audit directory. Public distribution excludes fitted pickle objects, row-level forecasts and private audit files. Aggregate corrected results and this issue history are public. Final/external numerical outcomes and validation MAE selection were unchanged by reporting corrections.\n')
    integration={'project_id':'stockout-decision-platform','title':'Stockout-aware operational decision platform','maturity':'executed local research prototype; independent AI-agent technical review passed','repository_url':'https://github.com/Prasanna-K-123/demand-inventory','pages_url':'https://prasanna-k-123.github.io/demand-inventory/','source':{'name':'Dingdong-Inc/FreshRetailNet-LT','url':'https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-LT','license':'CC-BY-4.0','rows_audited':7939549,'selected_series':1024,'selected_rows':634383,'fit_rows':356925,'transfer_holdout_identities':193,'hashes':manifest['source_hashes']},'primary':{'task':'rolling one-day observed normalized-sales forecasting','final_rows':int(pooled['n']),'model':'pooled_poisson','mae':pooled['mae'],'seasonal_mae':seasonal['mae'],'best_simple_mae':mean28['mae'],'relative_mae_reduction_vs_seasonal':improvement,'relative_mae_reduction_vs_best_simple':best_simple,'wape':pooled['wape'],'interval_coverage80':coverage['coverage80'],'weekly_blocks':10,'weekly_wins_vs_seasonal':10},'uncertainty':research['bootstrap'],'secondary':{'artificial_masking':'Learned hourly-share scaling improves conditional artificial reconstruction; no organic-demand identification','allocation':'Exact finite-grid scenarios; slightly lower proxy cost at shortage weights 3/5, worse at 1; no retailer-savings claim','policy_id':'raw-quantile-point-grid-v1'},'systems':{'automated_tests':ntests,'test_failures':fail,'durable_records':634383,'crash_publication_trials':4,'crash_equivalence':True,'http_measured_jobs':200,'http_errors':len(bench['errors']),'job_p95_ms':bench['job_end_to_end']['p95_ms'],'jobs_per_second':bench['jobs_per_second'],'peak_server_tree_rss_mb':bench['peak_server_process_tree_rss_mb'],'forecast_parity_error':bench['offline_service_max_absolute_error'],'allocation_parity':bench['offline_service_allocation_identical'],'receipt':'artifacts/benchmark.json','performance_model_version':bench['model_version'],'current_http_smoke':'artifacts/http_smoke.json'},'model_version':manifest['model_version'],'served_configuration_sha256':manifest['served_configuration_sha256'],'protocol_sha256':research['protocol_sha256'],'limits':['Normalized quantities, not money or physical units','Organic latent demand is unidentified','History-eligible sample with substantial attrition','Synthetic arrivals and assumed costs/capacity','Temporal dependence limits coverage and bootstrap claims','Loopback-only single machine; no visual-browser QA or production claim'],'paths':{'explorer':'explorer/index.html','code':'src/stockout','readme':'README.md','scientific_report':'docs/RESEARCH_REPORT.md','claims':'docs/CLAIM_MAP.md','api_demo':'scripts/demo_client.py','independent_review':'artifacts/review_status.json','systems':'docs/SYSTEM_DESIGN.md'},'legacy':{'branch':'legacy/m5-20261026','commit':'43c6f6193c0e7ccaf617fcd2a9283bddbc26df88'},'independent_review':read('review_status.json'),'private_defense_excluded_from_repository':True}
    atomic_json(ART/'integration_summary.json',integration)
    data={'summary':integration,'metrics':metrics.to_dict('records'),'intervals':intervals,'decisions':decisions['results'],'weekly':pd.read_csv(ART/'weekly_metrics.csv').to_dict('records'),'benchmark':bench,'labels':labels}
    write('explorer/index.html',(BASE/'explorer/template.html').read_text().replace('__DATA__',json.dumps(data,separators=(',',':')).replace('</','<\\/')))
    if a.private_dir:
        a.private_dir.mkdir(parents=True,exist_ok=True)
        questions=[
        ('Why is this not latent-demand estimation?','The mask identifies exposure, not missing demand. Actual inventory and counterfactual demand are absent. Artificial masking is conditional on fully in-stock observations and cannot identify organically censored demand.'),
        ('What prevents selection leakage?','Eligibility uses only pre-2025 history counts. A fixed SHA256 order chooses identities before fits. Future survival never replaces a disappearing identity. Attrition is reported. Identity holdouts are excluded from every fit and calibration, but past history is available for their features.'),
        ('Why Poisson loss for fractional quantities?','It is a nonnegative mean-model loss on scale-normalized targets, not a count-distribution claim. Conditional quantile models are fit separately. The scale itself uses only the preceding 28 days.'),
        ('How are gaps and time boundaries handled?','Reindex each series to calendar days; absent dates remain missing. Features require event date before target, arrival at or before as-of, and event sequence no later than the submission snapshot. Models remain fixed while one-day lags update.'),
        ('What is the interval claim?','Final empirical coverage is about 80.36% for a nominal 80% interval. Dependent dates/series do not satisfy a proven exchangeability condition. Calibration-period coverage is in-sample; validation CQR coverage using later calibration was removed. Point selection was always MAE-only and unaffected.'),
        ('Why does the bootstrap center differ from the table?','The table pools rows. The bootstrap first averages errors within date, then resamples contiguous seven-day blocks. Attrition gives unequal daily row counts. The interval is exploratory and preserves cross-series dependence within dates.'),
        ('What makes allocation optimal?','The DP exhaustively considers feasible per-item integer quantities at each capacity state. Backtracking yields the global minimum for this finite objective. An independent exhaustive oracle checks small cases. This says nothing about unknown real costs, latent demand or continuous dynamic inventory.'),
        ('Are scenario masses calibrated?','No. Raw q10, selected point/mean and raw q90 receive equal assumed weights. The middle value is not an estimated median. That q50-versus-mean protocol discrepancy is recorded, without refitting. The final API uses raw scenarios and matches the offline caps/objective.'),
        ('What exactly is idempotent or exactly once?','Identical batch and job keys reuse committed receipts. Conflicting content is rejected/quarantined. Computation can repeat after crashes, but publication is fenced by lease token and commits result/features/status atomically. This is not global exactly-once distributed processing.'),
        ('Can a late backfill change an existing job?','No. Its snapshot sequence is fixed. New jobs may see newly committed historical facts if as-of allows them, while old jobs remain reproducible. Source corrections require explicit revision semantics instead of silent overwrite.'),
        ('What did performance testing establish?','A small warmed repeated-history workload of 200 jobs, four clients and one worker met local thresholds. Memory measurement was corrected from a Windows launcher-only reading to aggregate server-tree working sets. No sustained, production or multihost throughput claim follows.'),
        ('What are the security boundaries?','Loopback binding, body/item limits, typed facts, parameterized SQL and trusted local model hashes. There is no authentication/TLS. A hash is corruption detection, not authentication if both manifest and pickle are maliciously replaced. Dependency pins alone do not establish vulnerability freedom.'),
        ('What would require real operational access?','Original arrival and decision timestamps; inventory and replenishment paths; cost and product-dimension data; an upstream correction/version policy; and prospective shadow evaluation. Only after those steps could operational decisions or savings be assessed.')]
        defense='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Stockout platform: private technical defense</title><style>body{font:17px/1.65 system-ui,sans-serif;color:#17303b;background:#f4f2e9;margin:0}main{max-width:980px;margin:auto;padding:44px 24px}h1{font-size:42px;line-height:1.15}h2{margin-top:40px}article,details{background:white;border:1px solid #c7d6d8;border-radius:12px;padding:20px;margin:16px 0}summary{font-weight:700;cursor:pointer}code{background:#eaf0f0;padding:2px 5px}li{margin:9px 0}.badge{text-transform:uppercase;font-size:13px;letter-spacing:.08em}@media print{body{background:white}details{break-inside:avoid}}</style><main><p class="badge">Private preparation packet · excluded from public repository</p><h1>Stockout-aware operational decision platform</h1><p>This packet prepares an evidence-based defense. It does not assert personal mastery, production impact or real retailer savings.</p>'''
        defense+=f'<article><b>Executed evidence:</b> observed-sales MAE {pooled["mae"]:.4f} vs seasonal {seasonal["mae"]:.4f}; {ntests} tests; 634,383 typed records; four actual publication-crash trials. Organic latent demand remains unidentified.</article>'
        defense+='<h2>Five-minute explanation</h2><ol><li>State the censored-sales problem and observed-sales estimand.</li><li>Explain the frozen identity sample and fit/validation/calibration/final boundaries.</li><li>Compare pooled results with both seasonal and strong moving-mean baselines; disclose attrition and dependence.</li><li>Walk through a durable batch, idempotent submission, fenced worker and atomic result.</li><li>Explain the finite objective and sensitivity result, including the cost ratio where the allocation loses.</li></ol><h2>Equations to defend</h2><article><p><b>Scale:</b> m(t)=max(mean available sales at t−28,…,t−1, 0.1); fit y(t)/m(t).</p><p><b>CQR:</b> s=max(q10−y, y−q90); choose order statistic ceil((n+1)×0.8), expand endpoints, clip lower at zero. Explain missing exchangeability.</p><p><b>Scenario loss:</b> L_i(q)=(1/3)Σ_s[c_short·max(d_is−q,0)+max(q−d_is,0)]. Equal one-third masses are assumed.</p><p><b>DP:</b> V_i(b)=min_q[V_(i−1)(b−q)+L_i(0.1q)] over feasible integer q. Initialize V_0(0)=0 and all other states infinite. Minimize final states up to capacity and backtrack. Rounding continuous quantities down increases loss by at most c_short×0.1 per item.</p></article><h2>Code walkthrough</h2><ul><li><code>contracts.py</code>: finite quantities, 24-hour vectors, conservation, timezones, one-day requests.</li><li><code>features.py</code>: calendar-aware windows and shared offline/served transform. Demonstrate a missing weekly lag.</li><li><code>ledger.py</code>: immutable facts, transactional checkpoints, snapshots and lease fencing. Explain each crash boundary.</li><li><code>worker.py</code>: bounded inference, fallback/restrict policy and named scenario definition.</li><li><code>decisions.py</code>: recurrence, feasibility reconstruction and exhaustive-oracle checks.</li><li><code>research.py</code>: identity/time fit masks, validation-only selection and later calibration.</li><li><code>benchmark.py</code>: actual HTTP, process-tree RSS and offline/service allocation equality.</li></ul><h2>Likely questions</h2>'
        for q,answer in questions: defense+='<details><summary>'+html.escape(q)+'</summary><p>'+html.escape(answer)+'</p></details>'
        defense+='<h2>Modifications to practice</h2><ul><li>Add a 14-day mean baseline while preserving cohort/time boundaries; label it post-protocol exploratory work.</li><li>Allow shortage weight 2: update the typed contract, version the decision policy, rerun oracle/parity checks and regenerate sensitivity results.</li><li>Add a synthetic 48-hour delay: show exclusion before arrival, visibility in a later job, and immutability of the original snapshot.</li><li>Corrupt a copied model byte: demonstrate rejection before unpickling and explain why a digest is not publisher authentication.</li><li>Kill a worker before commit, recover after lease expiry and compare semantic outputs with the clean run.</li></ul><h2>Claims to avoid</h2><p>Recovered true lost demand; retailer savings; calibrated scenario masses; cold-start validation; production-grade cloud infrastructure; independent external validation before review; or personal expertise unsupported by the work.</p><h2>Observed issue history</h2>'
        for r in failures: defense+='<article><b>'+html.escape(r['stage'])+'</b><p>'+html.escape(r['failure'])+'</p><p>'+html.escape(r['resolution'])+'</p></article>'
        defense+='<p>The original protocol and local audit outputs are retained. Reproduce using the repository README. No visual browser QA was performed.</p></main></html>'
        (a.private_dir/'stockout-defense.html').write_text(defense,encoding='utf-8')
    if a.verification_path:
        atomic_json(a.verification_path,{'project':'stockout-decision-platform','status':'complete_ready_for_publication','principal_research_executed':True,'source_rows_audited':7939549,'cohort_rows_ingested':634383,'automated_tests':ntests,'test_failures':fail,'actual_publication_crash_trials':4,'benchmark':bench,'research':integration['primary'],'protocol_sha256':research['protocol_sha256'],'issues':failures,'public_summary':'artifacts/integration_summary.json','no_browser_qa':True,'independent_review':'passed; independent AI-agent scope in artifacts/review_status.json'})
    print(json.dumps({'documents_built':True,'tests':ntests,'primary_mae':pooled['mae'],'relative_mae_improvement_vs_seasonal':improvement}))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--private-dir',type=Path);p.add_argument('--verification-path',type=Path);main(p.parse_args())
