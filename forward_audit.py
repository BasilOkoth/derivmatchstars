"""DigitMatchStar forward-only shadow evaluator.

Read-only: does not import the trading engine, access credentials, place orders,
change account settings, or modify executions. Python 3.10+, standard library.
Input JSONL: {"seq": 101, "digit": 3, "v1": 4, "ai": 3,
"fusion": 3, "predicted_at_seq": 100, "contract_id": "optional",
"official_result": "WIN" or "LOSS", "cycle_id": "optional",
"trade_no": 1}. Prediction fields in a record refer to the digit forecast
frozen at predicted_at_seq; they are scored ONLY if seq == predicted_at_seq + 1.
This is next-received-tick validation; a continuous market feed is not proven
by increasing local sequence numbers alone.
"""
from __future__ import annotations
import argparse
import collections
import json
import math
from pathlib import Path
from typing import Any

MODELS = ('v1', 'ai', 'fusion')

def _digit(x: Any):
    try:
        z=int(x)
        return z if 0 <= z <= 9 and str(x).strip() != '' else None
    except (TypeError, ValueError):
        return None

def wilson(success: int, total: int, z: float = 1.96):
    if not total:
        return None
    p=success/total
    den=1+z*z/total
    center=(p+z*z/(2*total))/den
    delta=z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/den
    return [round(max(0,center-delta),5),round(min(1,center+delta),5)]

def evaluate(rows: list[dict]) -> dict:
    totals={m: {'valid':0, 'hits':0,'skipped':0,'invalid_digit':0} for m in MODELS}
    official={'WIN':0,'LOSS':0,'OTHER':0,'disagreements':0}
    ids=set()
    cycles={}
    problems=collections.Counter()
    last_seq=None
    for index,row in enumerate(rows):
        try:
            seq=int(row['seq'])
            observed=_digit(row['digit'])
        except (KeyError,TypeError,ValueError):
            problems['invalid_observation']+=1
            continue
        if observed is None or seq <= 0:
            problems['invalid_observation']+=1
            continue
        if last_seq is not None:
            if seq <= last_seq:
                problems['nonincreasing_sequence']+=1
            elif seq > last_seq+1:
                problems['sequence_gaps']+=seq-last_seq-1
        last_seq=seq
        prior=row.get('predicted_at_seq')
        try: prior=int(prior)
        except (TypeError,ValueError): prior=None
        for model in MODELS:
            prediction=row.get(model)
            if prediction is None: continue
            predicted=_digit(prediction)
            if predicted is None:
                totals[model]['invalid_digit']+=1
                continue
            if prior is None or seq!=prior+1:
                totals[model]['skipped']+=1
                continue
            totals[model]['valid']+=1
            totals[model]['hits']+=int(predicted==observed)
        contract=str(row.get('contract_id') or '')
        result=str(row.get('official_result') or '').upper()
        if contract and result:
            if contract in ids:
                problems['duplicate_contract_record']+=1
            else:
                ids.add(contract)
                official[result if result in ('WIN','LOSS') else 'OTHER']+=1
                local=str(row.get('local_result') or '').upper()
                if local in ('WIN','LOSS') and local!=result:
                    official['disagreements']+=1
        cycle=row.get('cycle_id')
        trade=row.get('trade_no')
        if cycle is not None and result in ('WIN','LOSS'):
            try: n=int(trade)
            except (TypeError,ValueError): continue
            if n<1: continue
            c=cycles.setdefault(str(cycle),{'max_trade':0,'winner':None,'trades':set()})
            if n in c['trades']:
                problems['duplicate_cycle_trade']+=1
            c['trades'].add(n)
            c['max_trade']=max(c['max_trade'],n)
            if result=='WIN':
                if c['winner'] is not None and c['winner']!=n:
                    problems['multiple_winning_trades_in_cycle']+=1
                c['winner']=n
    results={}
    for name,s in totals.items():
        n=s['valid']; wins=s['hits']; rate=wins/n if n else None
        results[name]={**s,'accuracy':round(rate,5) if rate is not None else None,
                       'wilson_95':wilson(wins,n), 'chance_baseline':0.10}
    resolved=[c['winner'] for c in cycles.values() if c['winner'] is not None]
    unresolved=[c for c in cycles.values() if c['winner'] is None]
    cycle_stats={'total_observed':len(cycles),'resolved':len(resolved),
        'unresolved_or_censored':len(unresolved),
        'resolved_within_10':sum(x<=10 for x in resolved),
        'observed_over_10':sum(c['max_trade']>10 for c in cycles.values()),
        'resolved_depths':dict(sorted(collections.Counter(resolved).items()))}
    # Do not calculate a '10-trade success rate' using only resolved cycles:
    # unresolved or truncated cycles would bias it upward.
    return {'models':results, 'official_contracts':official,'cycle_depth':cycle_stats,
            'data_warnings':dict(problems),'market_continuity_verified':False,
            'note':'Execution unaffected. All metrics descriptive, not predictive guarantees.'}

def main():
    p=argparse.ArgumentParser(description='Forward-only shadow audit: no trading access')
    p.add_argument('jsonl',help='Input JSON lines with seq, digit, predictions, outcome metadata')
    p.add_argument('--output',help='Optional JSON report path')
    args=p.parse_args()
    data=[]
    with open(args.jsonl,encoding='utf-8') as f:
        for line_no,line in enumerate(f,1):
            if not line.strip(): continue
            try: value=json.loads(line)
            except json.JSONDecodeError as e: raise ValueError(f'Invalid JSON at line {line_no}') from e
            if not isinstance(value,dict): raise ValueError(f'Expected object at line {line_no}')
            data.append(value)
    report=evaluate(data)
    payload=json.dumps(report,indent=2)
    if args.output: Path(args.output).write_text(payload+'\n',encoding='utf-8')
    print(payload)

if __name__=='__main__':main()
