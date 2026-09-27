
# DigitMatchStar Premium Guided Video v5.4

This package includes the latest corrected production bot and an animated website CTA.

## Production bot
`bot-obfuscated.html` is based on:
`bot-obfuscated-v19-1-stream-sync-fixed.html`

It includes:
- V19 stream-sync trading behavior
- syntax/bracket repair from V19.1
- execution sound only during trading
- forward-analysis/research systems retained
- v5.2 safe recorder loader

## Animated website CTA
The outro now types the website progressively:
`w`
`ww`
`www.`
`www.digit...`
`www.digitmatchstar.com`

Then it holds the completed URL.

## Website CTA
Default:
https://www.digitmatchstar.com

Recommended Render env:
PUBLIC_WEBSITE_URL=https://www.digitmatchstar.com

## Render
Root Directory: media-worker
Build: pip install -r requirements.txt
Start: uvicorn app:app --host 0.0.0.0 --port $PORT

Expected health version:
premium-guided-v5.4
