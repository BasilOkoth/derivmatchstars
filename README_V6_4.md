
# DigitMatchStar Premium v6.4 — Robust One-Tap Telegram Buttons

Fixes the "Unknown action" issue.

New callback format:
- Approve: `a|<preview-id>`
- Reject: `r|<preview-id>`

The webhook also accepts legacy button formats:
- approve:<id>
- reject:<id>
- approve|<id>
- reject|<id>
- a:<id>
- r:<id>

So both new previews and older previews are supported.

The button stays fully inside Telegram:
- one tap approve
- one tap reject
- no browser
- no long signed link
- no second confirmation click

Important:
After deploying, confirm Telegram webhook still points to:
https://digitmatchstar-media-worker.onrender.com/telegram-webhook

Expected health version:
premium-guided-v6.4
