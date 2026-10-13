# Proposal rejection correction — complete repository

Fixed files: `app/engine.py`, `app/deriv_ws.py` (unchanged from previous full archive), and mirrored `engine.py`, `deriv_ws.py`.

The engine now refreshes the proposal AFTER tick-subscription setup and immediately before every DEMO purchase; it never attempts a BUY using a prearmed/cached quote. An explicitly rejected `InvalidContractProposal` is classified `INVALID_PROPOSAL_REJECTED`, rather than `BUY_UNCERTAIN_STOPPED`. Existing V7 logic may request another fresh proposal once. Genuine ambiguous BUY errors (timeouts/disconnects) still stop without retries.

To deploy: upload the ZIP contents (not the enclosing `derivmatchstars-main` directory) to the repository root, preserving folders. The Render Blueprint currently starts `uvicorn app.main:app`.

Check the deployed commit hash; a redeployment of older code won't contain these changes. Test DEMO before any other mode. Neither the original algorithm nor REAL execution permissions have been modified. This is not a proven fix until tested with Deriv.
