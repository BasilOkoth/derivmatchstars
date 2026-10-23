"""Reproducible shadow-only V1-inspired target persistence comparison.
Does not place or alter trades. Limited to tick history contained in user export.
"""
import json, csv, math, random
from collections import Counter
from pathlib import Path
SOURCE=Path('/mnt/data/digitmatchstar_current_tick_bias_R_10_2026-10-23T16-54-17-773Z.json')
raw=json.loads(SOURCE.read_text()); rows=raw['records']; digits=[rows[0]['sourceDigit']]+[r['actualNextDigit'] for r in rows]
assert all(rows[i]['actualSeq']==rows[i+1]['sourceSeq'] for i in range(len(rows)-1))

def score(history):
    # Core signals and weights of app/digit_score.py. Not byte-for-byte V1:
    # a small additional original-score term is not included in this proxy.
    n=len(history); current=history[-1]; last10=history[-10:]; last25=history[-25:]
    entropy25= -sum((v/len(last25))*math.log2(v/len(last25)) for v in Counter(last25).values())/math.log2(10)
    entropy10bits=-sum((v/len(last10))*math.log2(v/len(last10)) for v in Counter(last10).values())
    repeat10=sum(a==b for a,b in zip(last10,last10[1:]))/max(len(last10)-1,1)
    def freq(d,w):
        a=history[-w:];return a.count(d)/len(a)
    def transition(d,k):
        if n<k+1: return .1
        tail=tuple(history[-k:]); total=hits=0
        for i in range(n-k):
            if tuple(history[i:i+k])==tail:
                total+=1;hits+=history[i+k]==d
        return (hits+1)/(total+10)
    out=[]
    for d in range(10):
        f5,f10,f25,f50,f100=[freq(d,w) for w in (5,10,25,50,100)]
        gap=next((i for i,x in enumerate(reversed(history)) if x==d),50)
        moderate_gap=max(0,1-abs(min(gap,16)-6)/10)
        t1,t2=transition(d,1),transition(d,2)
        val=(42*(t1-.1)+24*(t2-.1)+16*(f5-.1)+12*(f10-.1)+7*(f25-.1)+4*(f50-.1)+2*(f100-.1)+8*(f5-f50)+5*(f10-f100)+2*moderate_gap+2*(current==d)*max(0,repeat10-.1)+int(f25<=.08 and entropy10bits<=2.5219280948873625)) * max(.55,1.15-.60*entropy25)
        out.append((d,val))
    return sorted(out,key=lambda a:(a[1],a[0]),reverse=True)

WARMUP=25; HORIZON=10
# Start cycles only where an entire 10-tick outcome is observed.
starts=list(range(WARMUP,len(digits)-HORIZON, HORIZON))
def test_sequence(digs):
    per=[]
    for start in starts:
        selections={}
        initially=score(digs[:start]); locked=initially[0][0]; adaptive=locked
        wins={k:None for k in ('dynamic','locked','adaptive')}
        switching=0
        for k in range(1,HORIZON+1):
            ranking=score(digs[:start+k-1]); dynamic=ranking[0][0]
            # adaptive persistence: switch only when a newly ranked digit leads
            # current target by >=3 score points; fixed rule before outcome.
            target_scores=dict(ranking)
            if target_scores[dynamic]-target_scores[adaptive]>=3.0:
                adaptive=dynamic;switching+=1
            for name,target in [('dynamic',dynamic),('locked',locked),('adaptive',adaptive)]:
                if wins[name] is None and digs[start+k-1]==target: wins[name]=k
        per.append({'start_seq':start+2,'initial_digit':locked,'dynamic_first_hit':wins['dynamic'],'locked_first_hit':wins['locked'],'adaptive_first_hit':wins['adaptive'],'adaptive_switches':switching})
    return per
out=test_sequence(digits)
summary={k:{'hit10':sum(x[f'{k}_first_hit'] is not None for x in out),'n':len(out),'avg_first_hit_given_hit':round(sum(x[f'{k}_first_hit'] for x in out if x[f'{k}_first_hit'] is not None)/max(1,sum(x[f'{k}_first_hit'] is not None for x in out)),2)} for k in ('dynamic','locked','adaptive')}
random.seed(17023)
N=3000
simulation={k:[] for k in summary}
for j in range(N):
    sim=[random.randrange(10) for _ in digits]
    ss=test_sequence(sim)
    for k in summary:simulation[k].append(sum(x[f'{k}_first_hit'] is not None for x in ss))
for k in summary:
    values=simulation[k];observed=summary[k]['hit10'];summary[k]['null_mean']=round(sum(values)/N,3);summary[k]['null_p_greater_equal']=round(sum(x>=observed for x in values)/N,3)
p=Path('/mnt/data/v1_persistence_results.json');p.write_text(json.dumps({'data':'User R_10 current tick bias export','note':'Approximate V1 core-score proxy; not exact deployed V1, and no contract settlements. Small sample, only complete non-overlapping 10-tick windows.','warmup':WARMUP,'horizon':HORIZON,'windows':out,'summary':summary},indent=2))
with open('/mnt/data/v1_persistence_windows.csv','w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(out[0]));w.writeheader();w.writerows(out)
print(json.dumps({'ticks':len(digits),'windows':len(out),'summary':summary,'rows':out},indent=2))
