"""Pre-normalize a bounded captured batch while network capture continues."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from scripts.research.event_research_pilot import read
from scripts.research.historical_filing_study import check,normalize_one
from tradingagents.research.filing_stability import validate_document


def run(root,count):
    check(root)
    receipt=read(root/'receipt.json');byhash={x.get('sha256'):x for x in receipt.values() if x.get('sha256')}
    tasks=[]
    for f in sorted((root/'documents').glob('*.json')):
        d=read(f)
        if (d['status']=='captured' and d['raw_sha256'] in byhash
            and not (root/'normalized'/f.name).exists()):tasks.append((root,f,byhash[d['raw_sha256']]))
        if len(tasks)>=count:break
    with ProcessPoolExecutor(max_workers=8) as pool:
        for i,_ in enumerate(pool.map(normalize_one,tasks),1):
            if i%50==0:print('Batch normalized',i,flush=True)
    counts=Counter();valid=0
    for _,f,_ in tasks:
        d=read(root/'normalized'/f.name);issues=validate_document(d,d['record']);counts.update(issues);valid+=not issues
    print({'batch':len(tasks),'structurally_valid_documents':valid,'issues':dict(counts)},flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--count',type=int,default=250)
    a=ap.parse_args();run(a.root,a.count)
