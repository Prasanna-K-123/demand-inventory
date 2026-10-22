# Forecasts, capital and inventory decisions

[![Public research checks](https://github.com/Prasanna-K-123/demand-inventory/actions/workflows/verify.yml/badge.svg)](https://github.com/Prasanna-K-123/demand-inventory/actions/workflows/verify.yml)

A reproducible historical M5 research case linking probabilistic forecasts to a constrained replenishment policy. The sample contains 210 item-store series across seven departments and three states. Data and future-period boundaries were fixed before fitting.

Start with the [decision memo](reports/DECISION_MEMO.md), [technical report](reports/TECHNICAL_REPORT.md), [diagnostic figure](reports/diagnostics.svg) or [offline explorer](docs/index.html). The explorer selects saved budget scenarios and shows affected order quantities. It does not refit models or invent observed retailer savings.

## Automated public checks

The automated checks run on public files without private data, credentials or model refitting. All **20 tests** cover the original nine scientific checks and eleven input-contract regressions, including 80 complete synthetic simulations checked against the preserved original implementation. Explorer arithmetic is checked separately. Raw-source model reproduction is separate.

The [22 October input-contract revision](docs/INPUT_CONTRACTS.md) rejects missing sales, invalid target windows, misaligned inputs and nonpositive or fractional delivery delays. Complete original and revised runs independently refit all four fixed models and reproduce the model bytes, forecasts and final analysis exactly. No forecast selection or reported result changed.

## Reproduce

Use the pinned Python requirements. Obtain the documented M5 ZIP from https://github.com/Nixtla/m5-forecasts/raw/main/datasets/m5.zip and the organizers' guide from https://github.com/Mcompetitions/M5-methods . Source data remain separate from any code license. No account/credential is embedded. With the cached inputs in data/raw:

```bash
python -m pip install -r requirements.txt
python scripts/prepare_data.py
PYTHONPATH=src python -m unittest discover -s tests -v
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1 python scripts/train_and_freeze.py
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1 python scripts/evaluate_final.py
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1 python scripts/verify_results.py
python scripts/report_results.py
node tests/check_explorer.cjs
```

The public source tree excludes raw sales rows, the processed panel and fitted artifacts. The preparation script reconstructs the fixed sample from the documented ZIP and rejects changed input bytes. Private recovery records retain the cached inputs and fitted artifacts. The raw ZIP/member hashes and schema normalization are recorded in reports/data_audit.json. A model freeze guards protocol/code/data, fitted models and final forecasts before evaluation. The original source bytes and freeze are retained under the documented revision; the integrity helper also verifies the exact revised source, input contracts and readable patch. Other frozen files must still match their original hashes. Do not alter parameters or choose another test-best comparator after scoring.

## Boundaries

Sales are observed; latent demand, inventory, costs, stockouts and lead times are not. Operating outcomes are simulations with explicit common capital/capacity constraints, not measured savings or a deployment. The final comparison spans only 15 weekly origins. Fourteen-day forecasting targets overlap; uncertainty resamples origins with all series together. This is not an official M5 leaderboard submission/rank.

The [live explorer](https://prasanna-k-123.github.io/demand-inventory/) has passed desktop, 375/320-pixel layout,
keyboard-control and report-link checks. A separate clean public-source run
retrained all four fixed quantile models from the pinned cached M5 ZIP; all
eleven frozen files and the final analysis reproduce byte for byte. See the
[release record](docs/RELEASE.md). See the [protocol](PROTOCOL.md) and [source guide](docs/SOURCES.md) for the fixed study and its data-use boundaries.
