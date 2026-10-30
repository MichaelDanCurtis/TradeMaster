"""Additional deterministic near-linear covariate challenge; original gates unchanged."""
import argparse,hashlib,json,math,os,subprocess
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[2]

def main():
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);args=p.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    rng=np.random.default_rng(59137);t=np.arange(256,dtype=np.float32);cases=[]
    for i in range(24):
        level=[.001,1.,100.,10000.][i%4]
        values=level*(1+.05*np.sin(t/(3+i%9))+.02*rng.standard_normal(256))
        market=400+t*np.float32([0,.01,-.01,1.][i%4])
        market=market+np.float32([0,1e-6,1e-4,.01][i//6])*rng.standard_normal(256)
        volume=np.float32(1e6)+t*np.float32(100)+np.float32([0,.01,1,100][i%4])*rng.standard_normal(256)
        cases.append({'label':f'near-linear-{i}','values':values.astype(np.float32).tolist(),'covariates':[market.astype(np.float32).tolist(),volume.astype(np.float32).tolist()]})
    env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','TMPDIR','LANG')};env.update(HF_HUB_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',OMP_NUM_THREADS='8')
    results=[]
    for horizon in (5,20):
        path=args.output/f'input-{horizon}.json';path.write_text(json.dumps({'horizon':horizon,'cases':cases}))
        outs={}
        for device in ('cpu','mlx'):
            runner=ROOT/'scripts/research'/('forecast_child.py' if device=='cpu' else 'forecast_mlx_child.py')
            python=ROOT/('.venv-timesfm' if device=='cpu' else '.venv-timesfm-mlx')/'bin/python'
            out=args.output/f'{device}-{horizon}.json'
            with out.with_suffix('.log').open('w') as log:
                subprocess.run([str(python),'-I',str(runner),str(path.resolve()),str(out.resolve()),str(ROOT/'.research-artifacts/forecast/model'),'--device',device],env=env,stdout=log,stderr=log,timeout=180,check=True)
            outs[device]=json.loads(out.read_text())
        for i,case in enumerate(cases):
            a=outs['mlx']['results'][i];b=outs['cpu']['results'][i]
            lhs=a['forecast']+[v for row in a['quantiles'] for v in row];rhs=b['forecast']+[v for row in b['quantiles'] for v in row]
            results.append({'horizon':horizon,'case':case['label'],'max_diff':max(abs(x-y) for x,y in zip(lhs,rhs)),
                            'passed':all(math.isclose(x,y,abs_tol=.001,rel_tol=.00001) for x,y in zip(lhs,rhs))})
    report={'seed':59137,'atol':.001,'rtol':.00001,'scope':'24 additional synthetic near-linear auxiliary series per horizon; positive target levels from 0.001 to 10000; no tuning on resulting forecasts',
            'results':results,'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in args.output.glob('*.json') if p.name!='report.json'}}
    (args.output/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps({'checks':len(results),'passed':sum(r['passed'] for r in results),'failures':[r for r in results if not r['passed']]},indent=2))
    if not all(r['passed'] for r in results):raise SystemExit('Additional near-linear qualification failed')

if __name__=='__main__':main()
