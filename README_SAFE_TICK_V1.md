# DigitMatchStar SAFE-TICK V1

## Frozen rule
Accept a candidate in shadow mode only when:

`candidateFreq25 <= 0.08 AND entropy10 <= 2.5219280948873625`

This rule uses only information available at the candidate tick.

## Discovery result
Completed aligned cohort:
- Finalized candidates: 100
- Overall STOP10: 32/100 = 32.0%
- SAFE-TICK V1 selected: 17/100 = 17.0%
- Selected candidates recurring by trade 10: 16/17 = 94.1%
- Selected STOP10: 1/17 = 5.9%
- Selected tail15: 0/17 = 0.0%

Selected discovery recurrence depths:
[7, 1, 2, 2, 4, 7, 8, 3, 2, 7, 4, 6, 5, 7, 13, 5, 10]

The single selected STOP10 case had a recurrence gap of 13.

## Important
This is a discovery rule. It was found by scanning the same 100-candidate dataset, so the result can be optimistic.

Do not tune the rule during the next validation cohort.

## Next validation
Run a fresh cohort of 500 candidate ticks with checkpoints at 100, 250 and 500.

For every candidate, record BEFORE the outcome:
- candidateFreq25
- entropy10
- SAFE-TICK V1 eligible yes/no
- shadow decision

Then observe:
- forwardGap
- STOP10 yes/no
- tail15 yes/no

Primary question:
Does the accepted group maintain a substantially lower STOP10 rate than the unfiltered group on untouched data?
