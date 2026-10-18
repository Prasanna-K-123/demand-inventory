# Source ledger

- M5 organizers: https://github.com/Mcompetitions/M5-methods . README explicitly links its public Drive collection with data, methods and evaluation resources for replication. Guide: https://raw.githubusercontent.com/Mcompetitions/M5-methods/master/M5-Competitors-Guide.pdf . Source guide SHA256 `f2650a2dbfb14d2c7d4482bda66c129ce5eec9341a76b76a833219559bf17109`.
- Nixtla mirror: https://github.com/Nixtla/m5-forecasts . It identifies the same organizers' public collection as the source and supplies a ZIP version. Download: https://raw.githubusercontent.com/Nixtla/m5-forecasts/main/datasets/m5.zip . ZIP50219189 bytes, SHA256 `cc704ba15d6802f8262e6ec7d4c6041e4ad6366a94365e8c84f721e450eed774`.
- Nixtla data loader documents that mirror: https://nixtla.github.io/datasetsforecast/m5.html . This is a maintained benchmark source, not scraped private retailer data.

Files used: sales_train_evaluation.csv, sell_prices.csv, calendar.csv. The mirror omits competition id/calendar d; the build explicitly constructs stable item__store keys and sequential day labels after checking consecutive dates. All ZIP members are hashed and read to verify CRC; only a fixed 210 series subset is analysed. No official M5 rank/metric is claimed.

Research/replication access is evidenced by the organizers' public distribution and documented mirror. This does not establish unrestricted third-party data redistribution or commercial-use permission. Raw data stay in private recovery records and must not be included under a future code license. Published artifacts should use own code and aggregate/derived results, with source attribution. No private inventory, stockout, cost or lead-time source exists in this case.

Price records are weekly prices in the historical benchmark. Forecast origins are checked to occur after that price week completes. The simulator's procurement, holding and lost-sales cost fractions, starting stock, lead time, cash and capacity rules are explicit assumptions. No present-day Walmart operating economics is inferred.

The organizers’ guide, page 5, defines weekly prices as seven-day averages. Page 8 explicitly measures the sales value in US dollars as units multiplied by price; this supports the USD reporting unit. Simulator cost fractions remain hypothetical.
