FULL replacement files for BasilOkoth/derivmatchstars.
Replace each file at the same relative path in GitHub. Preserve other files.
Change: reconnect stalled server feed when no first tick arrives, prevent overlapping reconnect tasks; classify stale server tick; show raw rank independent of >=9 execution gate.
IMPORTANT: The score >=9 restriction is unchanged. Rank 5 at 4.40 will be shown, but NO DEMO trade should execute at that score. Do not mistake this for ranking failure.
No changes to REAL automation or manual confirmation safeguards.
Compile/JS syntax tested only. Test with DEMO and monitor live server tick age.
