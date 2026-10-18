# Probabilistic demand and constrained replenishment

Frozen17October2026 before data profiling, model fitting or scoring. The M5 organizers' documented data are used through Nixtla's maintained ZIP mirror of their public research/replication files. No inventory, cost, stockout or lead-time data are supplied. Source observations remain separate from a future code license.

## Fixed sample and time boundaries

Select the lexicographically first10 item IDs in each of the7 M5 departments, crossed with stores CA_1, TX_1 and WI_1:70items,210series. Selection uses IDs/department metadata only, never sales or test outcomes. Keep all chosen series, including zeros, late introductions and interruptions. Outcomes are observed unit sales, not latent demand. Use sales_train_evaluation.csv days1–1941, calendar.csv and sell_prices.csv. The extra competition test files are not used. Do not claim the subset's metrics are official M5 scores/ranks.

Forecast14-day cumulative sales at weekly origins (origin is last observed day, forecast starts next day). Training origins364..1596 in increments7, with labels through1610. Calibration origins1624..1715 (14), development1743..1799 (9), final test1827..1925 (15). All origins divisible by7. Train labels end before calibration; calibration labels end before development; development labels end before test. Test labels end1939, within1941. Fifteen nonoverlapping weekly review periods are available for operational simulation; overlapping14-day forecast targets remain dependent. All test series/dates are retained.

## Frozen models and information set

Baseline1: seasonal naive expected14-day sales=2*last7day sales. Baseline2: Croston SBA, alpha=.1, initialized at first positive sale and updated only on observed days, with zero for no prior positive sale. Distributional baselines add training-calibration quantiles of (actual14-pointforecast)/max(last28day mean*14,1), pooled separately by department, to each point forecast times that same observed scale, then clip at zero. Calibration is separate from fit/development/test. No final-test recalibration.

Single challenger: four direct global HistGradientBoostingRegressor quantile models at .1/.5/.8/.9. learning_rate=.08,max_iter150,max_leaf_nodes15,min_samples_leaf50,l2_regularization5,max_bins128,early_stoppingFalse,random_state20261017. Categorical IDs use a training-only vocabulary for70items/7departments/3stores; unknown values are explicitly rejected. Feature defaults/imputation use training information only. No grid search, early stopping, architecture search or test-selected model changes. Each model is fitted once on training rows and remains frozen while later forecasts update observed lag features.

Features: item/store/department IDs; calendar month and deterministic sine/cosine day-of-year for the next day; observed sales totals over7/14/28/56days; most recent7-day versus preceding7-day ratio with denominator max(previous,1); zero-day fractions28/56; age since first positive sale as of origin, plus never-active flag; and **last price observed on or before origin**, with missing-price flag and training-median imputation for the model. No future realized price, future sales, unknown promotion, SNAP or event feature is used. Calendar dates are deterministic; no future realized covariate enters.

Raw quantile crossing is reported. Sort the four predictions within each series/origin, then clip at zero, as the predeclared coherence correction. Recheck pinball loss/coverage afterward. No hierarchy reconciliation is performed. Point errors use the median forecast. Primary forecast metric is mean pinball loss across the four quantiles (equal weight per series-origin). Report MAE, WAPE with actual denominator,80% interval coverage/width and .8-quantile calibration, by store/department and origin. Retain undercoverage rather than retune it away.

## Selection and frozen final evaluation

Select the baseline family on development mean pinball loss, ties1e-8 favour seasonal naive. Compare challenger with that selected baseline; ties favour baseline. Freeze source/protocol/training model/calibration/prediction hashes before exposing test scores. The same frozen forecasts feed the operating simulator; final metrics never change this forecast-model selection.

Primary final contrast is paired mean pinball challenger minus selected baseline. Uncertainty uses2000 circular moving-block bootstrap draws, blocks2 adjacent weekly origins; resample origins with all stores/items together, preserving within-origin dependence. Report a95% percentile interval, conditioning on fitted models and this fixed subset. Only15origins limits inference. Do not use an independent-policy bootstrap or claim national retailer effects.

## Inventory simulator

Review weekly. One-week lead time, one-week review interval: .8quantile of next14-day sales is the order-up-to target. At each weekly origin, receive last week's order, then order max(ceil(target)-onhand-outstanding,0); it arrives at next week's origin. Consume the following7days' observed sales as a demand proxy, with lost sales (no backlog). Start with zero onhand and zero pipeline: report startup separately and the full15weeks; no free initial stock. No refits or actual stock-state data.

Assumed unit procurement cost=.6*last observed selling price at order time. Missing price permits no order and is reported, not replaced with an invented cost. Holding cost=.1*last observed selling price per ending unit/week; lost-sales cost=.4*last observed selling price per missed unit. Price is a dated valuation input, not measured procurement economics.

Apply the same exogenous budget to each policy at each origin: budget multiplier in {.5,1,2} times expected weekly procurement spend estimated from last28day sales and known unit costs, with a total-unit order capacity2times observed trailing weekly unit volume across the sample. The primary operating scenario is multiplier1. Allocate desired integer orders by descending shortage-penalty/unit-cost, then lower current inventory coverage, then stable seriesID. Greedy allocation is a declared policy, not a proof of globally optimal inventory. Verify budgets/capacities after integer rounding. No future sales affect allocation. Unknown prices/costs are flagged.

Report holding+lost-sales penalty, unit fill rate, missed units, procurement spend, budget use, ending inventory and pipeline. Inventory purchase/spend is separate from the penalty objective; remaining stock is not treated as cash profit. Compare forecast rankings with operating rankings at the fixed cost/budget assumptions. Do not claim measured savings for Walmart.

## Failure checks and scope

Leakage: future sales/prices tampering must leave earlier-origin features unchanged. Timing: exact14day targets, delayed arrivals, stock conservation, no negative inventory, ordering respects common cash/capacity limits, no order with unknown costs. Known constant/intermittent sequences validate baseline recursions and quantile scoring.

Demand censoring: a separate deterministic scenario raises zero-sale weeks' demand proxy by25% of that series' trailing weekly average. This is not reconstructed true stockouts. Lead-time sensitivity uses2weeks and the unchanged14day target, explicitly a misspecified-policy robustness check rather than a reoptimized policy. Shortage penalty sensitivity=.2/.8 times selling price, holding unchanged. Shared fixed budgets and allocation assumptions remain explicit. Recommendations must state the conditions where they fail.

Deliver audited cached subset/build recipe, source and model freeze, baselines/challenger, fixed test metrics/uncertainty, constrained simulator, readable technical report, decision memo and an offline demonstration with budget control. Public tagged release and live browser verification remain a separate F gate. No automatic posting or outreach is included.
