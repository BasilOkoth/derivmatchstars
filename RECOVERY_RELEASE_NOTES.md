# Worker feed + contract recovery (2026-10-14)

- Subscriptions now check their actual client and elapsed time since the server received a tick.
- A stale feed triggers a bounded re-subscription; no purchases are allowed without a tick in the last 15 seconds.
- Persisted contracts continue to be probed for official Deriv settlement.
- Upon verified loss the next proposal takes the current server-side V1 top-ranked digit.
- Do not manually clear open contract IDs. Existing BUY_CLAIM protections remain.
- No changes to browser controls; REAL automated buys remain disabled.
- Check logs: DMS_FEED_RECOVER, DMS_EXECUTION_TARGET, DMS contract reconciliation failed.
- Python syntax validation only, not a successful Deriv DEMO end-to-end test.
