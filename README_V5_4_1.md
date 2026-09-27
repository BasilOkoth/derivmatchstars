
# DigitMatchStar v5.4.1 — Single Recorder Fix

This release fixes duplicate recorder controls.

Changes:
- Only `screen-recorder-safe-v5-2.js` is included.
- `bot-obfuscated.html` contains exactly one recorder loader.
- The active recorder removes/hides legacy recorder panels such as `dms43-panel`.
- A short startup guard catches an old cached recorder script that loads slightly later.
- Latest V19.1 production bot remains the base.
- v5.4 typed website CTA, moderation and premium video worker remain unchanged.

After uploading:
1. Replace `bot-obfuscated.html`.
2. Replace `screen-recorder-safe-v5-2.js`.
3. Delete old recorder files/references if present, especially:
   - `screen-recorder-safe-v4-3.js`
   - `screen-recorder-safe-v5.js`
4. Hard-refresh the browser (Ctrl+Shift+R).
