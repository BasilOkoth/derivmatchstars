UPLOAD THROUGH GITHUB (NO LOCAL TERMINAL)

1. In BasilOkoth/derivmatchstars, click Add file > Create new file.
2. Name the new file exactly:
   .github/workflows/apply-digitmatchstar-fix.yml
3. Paste the FULL contents of this ZIP's matching YAML file; commit on main.
4. Go to Actions > Apply DigitMatchStar startup and REAL router fix > Run workflow.
5. The workflow updates the COMPLETE current app/__init__.py and app/main.py in place and commits them.
6. Once committed, Render deploys the updated main branch if autodeploy is enabled.
7. Test /health, DEMO logic and REAL manual routes without risking real funds before placing any live order.

This deliberately preserves all current engine, V5-V8 ranking enhancements and DEMO-only
unattended trading safeguards. It registers the already uploaded app/real_manual.py.
REAL orders remain individually confirmed; no unattended REAL recovery is enabled.

IMPORTANT: This is an ACTIONS WORKFLOW, not a replacement copy of older files.
It generates the full updated files directly from latest GitHub main.
GitHub branch protection or Actions permissions may block automated push.
If so, configure Actions workflow permissions for read/write or use a PR.
