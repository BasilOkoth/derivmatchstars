# DigitMatchStar Safe Live Observer v4.1

This replaces the previous v4 recorder integration approach.

## Important

This recorder is designed specifically so it **does not modify the trading bot**.

It does NOT:

- replace `cyclePerformance.startCycle`
- replace `cyclePerformance.completeCycle`
- wrap proposal/buy handlers
- modify WebSocket functions
- change stake calculations
- change max trades
- call `startCycle` or `completeCycle`
- change `cyclePerformance.current`
- change cycle history

It only **reads** cycle state every 250 ms.

## How it detects a cycle

The observer looks at:

```js
window.cyclePerformance.current
```

When that changes from empty to a cycle, recording starts.

When it returns to empty, recording stops.

It also reads completed cycle history, when available, only to obtain the final metadata that is sent to the existing premium video worker.

## Production bot

Your production bot is:

```text
bot-obfuscated.html
```

Do not replace that file with `bot.html`.

## Integration

Upload:

```text
screen-recorder-safe-v4-1.js
```

to the repository root.

Then load that standalone file from `bot-obfuscated.html` immediately before the closing body tag:

```html
<script src="/screen-recorder-safe-v4-1.js"></script>
```

Remove/avoid older recorder script tags so only this observer is active.

## What you should see

When the page loads:

```text
SAFE LIVE CAPTURE
READ-ONLY OBSERVER · TRADING LOGIC UNTOUCHED
```

Click:

```text
Enable live capture
```

Chrome/Edge asks you which screen/tab to share.

Choose the DigitMatchStar bot tab.

Then:

```text
Ready · safely observing next cycle
```

When a cycle appears:

```text
● RECORDING ACTUAL BOT SCREEN
```

When the bot itself finishes the cycle, the observer notices that state transition and stops its own MediaRecorder approximately 1.6 seconds later.

## Failure isolation

If:

- recording fails,
- browser permission is denied,
- upload fails,
- Render is offline,
- Telegram is unavailable,

the trading bot keeps operating. This recorder does not sit in the execution path.

## Existing backend

This observer continues to use the existing:

```text
/api/live-capture-ticket
```

and Render `/compose-live` endpoint from v4, so your media-worker backend does not need to be redesigned just to adopt the safer observer.
