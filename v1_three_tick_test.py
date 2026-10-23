import importlib.util, json
from pathlib import Path
spec=importlib.util.spec_from_file_location('v1stud','/mnt/data/v1_persistence_study.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
d=mod.digits; out=[]
for start in mod.starts:
    hits={'dynamic':None,'three_tick':None,'locked10':None}
    locked=mod.score(d[:start])[0][0]; target=locked
    for k in range(1,11):
        hist=d[:start+k-1]
        dynamic=mod.score(hist)[0][0]
        if (k-1)%3==0: target=dynamic
        actual=d[start+k-1]
        for name,pick in [('dynamic',dynamic),('three_tick',target),('locked10',locked)]:
            if hits[name] is None and pick==actual: hits[name]=k
    out.append({'start_seq':start+2,**hits})
print(json.dumps(out,indent=2)); print('summary:',{m:{'hits':sum(x[m] is not None for x in out),'mean_hit':round(sum(x[m] for x in out if x[m] is not None)/sum(x[m] is not None for x in out),2)} for m in ('dynamic','three_tick','locked10')})
Path('/mnt/data/v1_three_tick_results.json').write_text(json.dumps({'method':'V1-inspired proxy, R_10 retrospective, 6 non-overlapping windows, 25-tick warmup, no contract outcomes','windows':out},indent=2))
