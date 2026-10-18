# Forecasts, capital and inventory decisions

A reproducible historical M5 research case linking probabilistic forecasts to a constrained replenishment policy. The sample contains 210 item-store series across seven departments and three states. Data and future-period boundaries were fixed before fitting.

Start with the [decision memo](reports/DECISION_MEMO.md), [technical report](reports/TECHNICAL_REPORT.md), [diagnostic figure](reports/diagnostics.svg) or [offline explorer](docs/index.html). The explorer selects saved budget scenarios and shows affected order quantities. It does not refit models or invent observed retailer savings.

## Reproduce

Use the pinned Python requirements. Obtain the documented M5 ZIP from https://github.com/Nixtla/m5-forecasts/raw/main/datasets/m5.zip and the organizers' guide from https://github.com/Mcompetitions/M5-methods . Source data remain separate from any code license. No account/credential is embedded. With the cached inputs in data/raw:

```bash
python scripts/prepare_data.py
PYTHONPATH=src python -m unittest discover -s tests -v
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1 python scripts/train_and_freeze.py
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1 python scripts/evaluate_final.py
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1 python scripts/verify_results.py
python scripts/report_results.py
node tests/check_explorer.cjs
```

The public source tree excludes raw sales rows, the processed panel and fitted artifacts. The preparation script reconstructs the fixed sample from the documented ZIP and rejects changed input bytes. Private recovery records retain the cached inputs and fitted artifacts. The raw ZIP/member hashes and schema normalization are recorded in reports/data_audit.json. A model freeze guards protocol/code/data, fitted models and final forecasts before evaluation. Do not alter parameters or choose another test-best comparator after scoring.

## Boundaries

Sales are observed; latent demand, inventory, costs, stockouts and lead times are not. Operating outcomes are simulations with explicit common capital/capacity constraints, not measured savings or a deployment. The final comparison spans only 15 weekly origins. Fourteen-day forecasting targets overlap; uncertainty resamples origins with all series together. This is not an official M5 leaderboard submission/rank.

The explorer has script and static-link checks. Rendered/live browser verification, public hosting and a version tag remain in the [release checklist](docs/RELEASE.md). See the [protocol](PROTOCOL.md) and [source guide](docs/SOURCES.md) for the fixed study and its data-use boundaries.
