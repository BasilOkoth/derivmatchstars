# Tick DNA → Tail Risk Lab v1.0

Forward-only, 20-cycle, demo-only research add-on for DigitMatchStars.

## Upload these files

1. Replace `deriv-live-bridge.js`
2. Replace `research-suite-loader.js`
3. Add new `tick-dna-tail-lab-v1.js`

No other file needs to be changed if your current deployment already loads `deriv-live-bridge.js` and `research-suite-loader.js`.

## What the lab records

For each of exactly 20 future cycles:

- the full formatted tick value, not just the last digit
- integer and decimal digit positions
- last, second-last and third-last digit
- digit sums, uniqueness, repeated adjacent digits
- odd/even and high/low composition
- within-tick digit-step structure
- quote change, direction and magnitude from the prior tick
- last-digit transitions
- rolling state over 5, 10, 25, 50 and 100 ticks
- cycle snapshots at T0, T3, T5, T7, T10, T12 and T15
- final depth and labels: >5, >10, >12 and reached 15

## Important design rule

The cohort is shadow-only. The Tick DNA lab does not place, stop, extend, block, retry or size any trade. This prevents the experiment from changing the outcomes it is trying to measure.

## Run the test

1. Deploy the three files.
2. Open the bot on a Deriv demo/virtual account.
3. Keep the same market for the entire cohort.
4. Open the `Tick DNA → Tail Risk Lab` panel.
5. Click **ARM 20-CYCLE TEST** before the next cycle begins.
6. Let all 20 cycles complete under your existing cycle rules.
7. Click **EXPORT JSON**.
8. Send the exported JSON back for analysis.

The lab automatically stops accepting new cohort cycles after the 20th completed cycle.

## Why this version is different

The original Tail Risk model mainly uses gap/frequency/tail-trajectory variables. This experiment preserves the raw numerical tick structure so we can test whether any stable information exists in the entire tick state before a deep tail develops.

A useful result is not merely a pattern in these 20 cycles. Any promising rule discovered from this cohort must then be frozen and tested on a new unseen forward cohort.
