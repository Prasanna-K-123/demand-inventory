# Claim-to-evidence map

| Allowed claim | Evidence under artifacts/ unless code | Boundary |
| --- | --- | --- |
| Observed-sales forecast improvement | forecast_metrics.csv; weekly_metrics.csv; bootstrap.json | Bounded observed rows; one-day rolling forecasts |
| Measured interval coverage | interval_metrics.json | Empirical temporal coverage, no exchangeability guarantee |
| Artificial reconstruction improvement | artificial_masking.json | Conditional in-stock masks, not organic lost demand |
| Exact finite-grid objective | decision_summary.json; tests.xml; decisions.py | Declared scenarios/caps only; cost sensitivity includes a loss |
| Durable conservation | ledger_ingestion_receipt.json | 634,383 real records; synthetic arrival schedule |
| Crash/restart equivalence | recovery_receipt.json; tests.xml | Actual local process exits; not distributed failover |
| Future-data exclusion and feature parity | tests.xml; benchmark.json | Event date, arrival as-of and fixed input snapshot |
| Local performance thresholds | benchmark.json | 200 measured jobs after warm-up, four clients; environment and unmeasured telemetry in receipt |

Do not claim organic latent-demand recovery, retailer savings, physical-unit or money accuracy, cold-start validation, calibrated scenario masses, production impact, personal mastery or independent external validation before review.
