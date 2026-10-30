"""Offline model-only challenger inference. Inputs contain no realized target values."""
import argparse
import json
import random
import resource
import time
import sys
from pathlib import Path

import numpy as np
import torch


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--kind',choices=['chronos2','kronos-small','kronos-base','sundial'],required=True)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--model',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--code',type=Path)
    parser.add_argument('--tokenizer',type=Path)
    args=parser.parse_args()
    torch.set_num_threads(8);torch.set_num_interop_threads(1)
    packet=json.loads(args.input.read_text())
    if packet['horizon']!=5:raise ValueError('This qualification uses exactly five sessions')
    start=time.perf_counter()
    if args.kind=='chronos2':
        from chronos import Chronos2Pipeline
        model=Chronos2Pipeline.from_pretrained(str(args.model),device_map='cpu',torch_dtype=torch.float32,local_files_only=True)
        model.model.eval()
    elif args.kind.startswith('kronos'):
        import pandas as pd
        sys.path.insert(0,str(args.code))
        from model import Kronos,KronosTokenizer,KronosPredictor
        weights=Kronos.from_pretrained(str(args.model),local_files_only=True).eval()
        tokenizer=KronosTokenizer.from_pretrained(str(args.tokenizer),local_files_only=True).eval()
        model=KronosPredictor(weights,tokenizer,device='cpu',max_context=512,clip=5)
    else:
        from transformers import AutoModelForCausalLM
        model=AutoModelForCausalLM.from_pretrained(str(args.model),trust_remote_code=True,local_files_only=True,torch_dtype=torch.float32).eval().to('cpu')
    loaded=time.perf_counter();results=[]
    print(json.dumps({'state':'loaded','kind':args.kind,'load_seconds':loaded-start}),flush=True)
    with args.output.with_suffix('.jsonl').open('x') as journal:
        for index,case in enumerate(packet['cases']):
            seed=59137+int(case['case_id']);random.seed(seed);np.random.seed(seed);torch.manual_seed(seed)
            began=time.perf_counter()
            with torch.inference_mode():
                if args.kind=='chronos2':
                    item={'target':np.asarray(case['values'],dtype=np.float32)}
                    if case.get('covariates') is not None:
                        item['past_covariates']={k:np.asarray(v,dtype=np.float32) for k,v in zip(['market','volume'],case['covariates'])}
                    # One window per call and explicit isolation prevent cross-window learning.
                    output=model.predict([item],prediction_length=5,context_length=256,cross_learning=False)[0][0].float().cpu().numpy()
                    quantiles={str(q):output[model.quantiles.index(q)].tolist() for q in [.1,.5,.9]}
                    forecast=quantiles['0.5'];extra={'quantiles':quantiles}
                elif args.kind.startswith('kronos'):
                    df=pd.DataFrame(case['ohlcva'],columns=['open','high','low','close','volume','amount'])
                    pred=model.predict(df,pd.Series(pd.to_datetime(case['dates'])),pd.Series(pd.to_datetime(case['target_dates'])),
                        pred_len=5,T=.6,top_k=0,top_p=.9,sample_count=10,verbose=False)
                    forecast=pred['close'].tolist();extra={}
                else:
                    output=model.generate(torch.tensor([case['values']],dtype=torch.float32),max_new_tokens=5,num_samples=20,revin=True)
                    samples=output[0].float().cpu().numpy()
                    if samples.shape!=(20,5):raise ValueError(f'Unexpected sample shape {samples.shape}')
                    forecast=np.median(samples,axis=0).tolist()
                    extra={'sample_mean':samples.mean(axis=0).tolist(),'quantiles':{'0.1':np.quantile(samples,.1,axis=0).tolist(),'0.9':np.quantile(samples,.9,axis=0).tolist()}}
            if len(forecast)!=5 or not np.isfinite(forecast).all():raise ValueError('Incomplete or nonfinite forecast')
            row={'case_id':case['case_id'],'forecast':forecast,'seed':seed,'inference_seconds':time.perf_counter()-began,**extra}
            journal.write(json.dumps(row)+'\n');journal.flush();results.append(row)
            if (index+1)%20==0 or index+1==len(packet['cases']):
                print(json.dumps({'kind':args.kind,'completed':index+1,'total':len(packet['cases']),'elapsed_seconds':time.perf_counter()-loaded}),flush=True)
    args.output.write_text(json.dumps({'kind':args.kind,'device':'cpu','dtype':'float32','torch':torch.__version__,
        'load_seconds':loaded-start,'total_seconds':time.perf_counter()-start,
        'peak_rss_mb':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024**2,'results':results},indent=2)+'\n')

if __name__=='__main__':main()
