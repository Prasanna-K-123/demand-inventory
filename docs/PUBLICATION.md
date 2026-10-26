# Public release preparation

Only the paths in public_allowlist.json are intended for publication. Raw data, fitted pickle files, row-level forecasts, runtime databases, private audit notes and test caches are excluded.

The public JUnit receipt preserves every test identity, pass/skip status and timing. Workspace paths and host metadata have been removed for publication; the original receipt is retained privately. This does not rerun or alter a test.

The self-contained explorer is copied identically to docs/index.html to support the repository's existing Pages configuration. The explicit deployment workflow also uploads that same explorer. Neither destination hosts the local Python service.

GitHub Actions are pinned to official repository commit identities resolved on 26 October 2026. The source package does not establish publication by itself; verify the resulting main branch, checks and live page after publishing.
