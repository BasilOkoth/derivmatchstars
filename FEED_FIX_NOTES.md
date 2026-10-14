# Server tick feed recovery fix

Full replacement of `app/__init__.py` and original repo files.

- Repairs missing/stale tick subscriptions without launching unlimited concurrent recovery tasks.
- Rebuilds stale ranking history even when the stored buffer is full.
- Logs recovery exceptions instead of silently swallowing them.
- Blocks new first trades and recovery trades while canonical server ticks are older than 15 seconds.
- Preserves the >=9 score gate, ranking and DEMO-only purchase permissions.

**Checks:** Python compile only. Neither Deriv network operation nor Render deployment was tested. Restart Render after updating and verify that the server epoch advances in sync with the browser.
