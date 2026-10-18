# Forecast-to-order decision memo

17 October 2026 · Historical retail data and hypothetical operating costs

Retain the development-selected global quantile model for this research case. Final pinball loss is 36.53% lower than the development-selected Croston baseline. The paired difference is -0.9260, 95% two-origin block interval [-1.2617, -0.6191], conditional on the frozen models and only 15 weekly origins.

The operating objective changes the ranking among simple methods: seasonal naive forecasts better than Croston in the final period but incurs a greater simulated penalty. The global model has the lowest primary penalty, USD 11,194.18, while its 76.95% fill rate is slightly below seasonal naive. The correct choice depends on explicit service/capital/cost priorities.

Do not present the penalty reduction as actual retailer savings. Costs, inventory starting empty, one-week lead time, loss treatment, cash budgets and greedy allocation are imposed assumptions. Zero sales are not proven unconstrained demand. Check the fixed lower/higher budget, longer lead-time, shortage-cost and censoring cases before generalizing. Procurements, terminal stock and pipeline are separately reported.

The next operational requirement is real stock, cost, delivery and lost-sales data. The current deliverable is a reproducible benchmark and policy simulator, with an offline explorer. It is not a deployed forecast/order system or an official M5 ranking. See [technical report](TECHNICAL_REPORT.md) and [fixed evidence](final.json).
