# DigitMatchStar TailGuard Research v2 — Demo Autopilot

This version is designed for clean forward research without needing to manually start each research cycle.

## Core behavior

The runner uses the existing DigitMatchStar engine. It does not create a second trading engine or call Deriv purchase APIs itself.

It will:

- require a confirmed **DEMO** account;
- select **AI AUTO** when the mode control is discoverable;
- target a **10-trade cycle cap** through the visible bot control when discoverable;
- start the existing bot automatically;
- count newly completed cycles;
- stop after **5 completed cycles per local calendar day**;
- resume with a fresh daily counter on the next local day;
- immediately stop if the account changes to REAL or cannot be confirmed as DEMO.

## TailGuard research

The existing shadow TailGuard remains intact:

- Entry: PASS / SHADOW_REJECT
- Trade 3: monitor
- Trade 5: GREEN / AMBER / SHADOW_STOP
- Trade 7: GREEN / AMBER / SHADOW_STOP

These signals are still research hypotheses. They are logged but they do not yet alter the trading engine.

## Why shadow mode remains important

The first clean report contained only a very small number of naturally resolved tails. Automatically enforcing those thresholds now would risk fitting the existing sample rather than validating the rule. This version therefore automates **data collection**, not unvalidated live decision rules.

## Daily research target

The default is:

- 5 completed cycles/day
- AI AUTO
- 10-trade cycle target
- DEMO only

At 30 days, that can produce up to 150 forward cycles, enough to compare T5/T7/T10 behavior much more meaningfully than the initial sample.

## Files

- `tailguard-research-v2-autopilot.js`
- `TAILGUARD_AUTOPILOT_INSTALL.txt`
