# DigitMatchStar Shadow Audit — complete standalone source

This package is a **complete and executable read-only analysis module**. It is *not* a replacement of the existing multi-thousand-line `app/engine.py`, and it makes **zero changes** to execution paths, including DEMO and REAL. It neither claims to fix settlement handling nor a 10-trade win limit.

## Input

Create a JSONL log containing one JSON object per received tick, with `seq`, `digit`, `predicted_at_seq`, and optional `v1`, `ai`, `fusion`, `contract_id`, `official_result`, `local_result`, `cycle_id` and `trade_no` keys. These values must be recorded at the moment predictions are frozen rather than reconstructed after an outcome. Existing repository exports may need mapping to this schema.

Example:

```json
{"seq":101,"digit":7,"predicted_at_seq":100,"v1":7,"ai":2,"fusion":7,"cycle_id":"C1","trade_no":1,"contract_id":"123","official_result":"WIN","local_result":"WIN"}
```

Use `python forward_audit.py ticks.jsonl --output report.json`; test with `python -m unittest discover -s tests -v` from inside package directory.

### Limitations

- Strict local sequence adjacency does not prove that the real market did not skip ticks during connection loss.
- Only authoritative settled contracts should count toward contract performance. The module counts unique contract IDs.
- Never train models on the validation period or choose settings after looking at the outcomes.
- We did not modify your production GitHub branch. A GitHub permission error blocked creation of a separate review branch.
- This research module can establish evidence; no method here guarantees a match by 10 trades.
