"""Read-only stage captures for the unchanged qualification inputs and model."""
import argparse,json,sys,time,inspect
from pathlib import Path
import numpy as np

p=argparse.ArgumentParser();p.add_argument('device',choices=['cpu','mps','mlx']);p.add_argument('output',type=Path);p.add_argument('--reference-trend',type=Path);args=p.parse_args()
root=Path(__file__).resolve().parents[2]
packet=json.loads((root/'.research-artifacts/forecast/mlx-benchmark/input-5.json').read_text())
data={};label='';started=time.perf_counter()
if args.device in ('cpu','mps'):
    import torch
    from timesfm3 import ModelConfig,TimesFM3Evaluator
    torch.set_num_threads(8);torch.set_num_interop_threads(2)
    model=TimesFM3Evaluator(ModelConfig(checkpoint_path=str(root/'.research-artifacts/forecast/model'),device=args.device,per_core_batch_size=1,local_files_only=True))
    def save(key,x):data[label+'/'+key]=x.detach().cpu().numpy()
    original=model.model._preprocess
    def preprocess(values,masks,*a,**kw):
        save('values',values);save('masks',masks)
        result=original(values,masks,*a,**kw)
        save('normalized',result[0]);save('embedding',result[1]);save('mu',result[3][0]);save('sigma',result[3][1])
        return result
    model.model._preprocess=preprocess
    decode_code=inspect.unwrap(model.model.decode.__func__).__code__
    def profile(frame,event,arg):
        if frame.f_code is decode_code and event=='return':
            for key in ('m_trend','c_trend','apply_detrend'):save(key,frame.f_locals[key].squeeze(-1))
    sys.setprofile(profile)
    for case in packet['cases']:
        label=case['label'];values=np.asarray(case['values'],dtype=np.float32);cov=case.get('covariates')
        output=list(model.predict_batch([values],horizon=5,past_only_covariates=[np.asarray(cov,dtype=np.float32)] if cov else None,return_quantiles=True,use_symmetric_averaging=False,make_positive=True,sort_quantiles=True))[0]
        data[label+'/output']=np.asarray(output.quantiles).reshape(5,9)
    sys.setprofile(None)
else:
    import mlx.core as mx
    import mlx_tsfm.models.timesfm as port
    mx.set_default_device(mx.gpu)
    model=port.TimesFM3();model.load_weights(str(root/'.research-artifacts/forecast/model/model.safetensors'),strict=True);mx.eval(model.parameters())
    def save(key,x):mx.eval(x);data[label+'/'+key]=np.asarray(x)
    reference=np.load(args.reference_trend) if args.reference_trend else None
    original_detrend=model._detrend
    def detrend(*a):
        result=original_detrend(*a) if reference is None else tuple(mx.array(reference[label+'/'+k]) for k in ('m_trend','c_trend','apply_detrend'))
        for key,x in zip(('m_trend','c_trend','apply_detrend'),result):save(key,x)
        return result
    model._detrend=detrend
    original_forward=model._forward_fn()
    def forward(values,masks,targets,cpm):
        save('values',values);save('masks',masks)
        _,mu,sigma=port._get_running_stats(values,masks);save('mu',mu);save('sigma',sigma)
        normalized=mx.where(masks,0.,port._revin(values,mu,sigma))
        zeros=mx.zeros((*values.shape[:-1],model.config.output_patch_len))
        # All variates in these inputs are past-only; future features are fully masked.
        combined=mx.concatenate([normalized,zeros,masks.astype(mx.float32),mx.ones_like(zeros)],axis=-1)
        save('normalized',combined);save('embedding',model.pre_transformer_resblock(combined))
        return original_forward(values,masks,targets,cpm)
    model._forward_fn=lambda:forward
    for case in packet['cases']:
        label=case['label'];values=np.asarray(case['values'],dtype=np.float32)[None,:];cov=case.get('covariates')
        if cov:values=np.concatenate([values,np.asarray(cov,dtype=np.float32)])
        out=model.decode(mx.array(values[None,:,:]),5);mx.eval(out)
        data[label+'/output']=np.maximum(np.sort(np.asarray(out[0,0]),axis=-1),0)
np.savez(args.output,**data)
print(args.device,'stages',len(data),'seconds',time.perf_counter()-started)
