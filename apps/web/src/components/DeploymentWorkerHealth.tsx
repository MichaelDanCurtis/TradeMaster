"use client";

import { useEffect, useState } from "react";
import { deploymentRequest, type DeploymentWorkerRuntime } from "@/lib/deployments";

const label = (value:string) => value.replaceAll("_", " ");

export function DeploymentWorkerHealth({accountKey}:{accountKey?:string}) {
  const [runtime,setRuntime]=useState<DeploymentWorkerRuntime|null>(null);
  const [error,setError]=useState("");
  const [revision,setRevision]=useState(0);
  useEffect(()=>{
    const controller=new AbortController();
    let timer:ReturnType<typeof setTimeout>|undefined;
    setRuntime(null);setError("");
    async function poll() {
      try {
        const value=await deploymentRequest<DeploymentWorkerRuntime>(`/runtime${accountKey?`?account_key=${encodeURIComponent(accountKey)}`:""}`,undefined,controller.signal);
        if(!controller.signal.aborted){setRuntime(value);setError("");}
      }catch(e){if(!controller.signal.aborted){setRuntime(null);setError(e instanceof Error?e.message:"Worker health unavailable");}}
      finally{if(!controller.signal.aborted)timer=setTimeout(poll,5000);}
    }
    void poll();
    return ()=>{controller.abort();if(timer)clearTimeout(timer);};
  },[accountKey,revision]);
  return <section aria-label="Deployment worker health">
    <h3>Account observation and evaluation worker</h3>
    <p>{error||runtime?.message||"Checking saved worker heartbeat…"}</p>
    <button type="button" onClick={()=>setRevision(value=>value+1)}>Refresh worker health</button>
    {runtime?<>
      <p>{accountKey?"Selected account":"All accounts"}: {runtime.queued} queued · {runtime.running} running evaluations. A heartbeat does not establish fresh account data or grant order approval.</p>
      {runtime.workers.length?<details><summary>Worker details ({runtime.workers.length})</summary><ul>{runtime.workers.map(worker=><li key={worker.worker_id}>
        <p>{label(worker.status)} · {worker.mode==="evaluate"?"Evaluations enabled":"Reconciliation only"}. Last heartbeat: {new Date(worker.last_seen_at).toLocaleString()}.</p>
        {worker.last_result?<p>Last cycle: {label(worker.last_result.status)}{worker.last_result.error_type?` (${worker.last_result.error_type})`:""}.{worker.last_result.account?` Reconciled drawdown ${worker.last_result.account.drawdown_available?"available":"unavailable"}.`:""}</p>:<p>No cycle result has been recorded.</p>}
        {worker.last_result?.message?<p>{worker.last_result.message}</p>:null}
        {worker.last_result?.account?.observed_at?<p>Account observed: {new Date(worker.last_result.account.observed_at).toLocaleString()}.</p>:null}
        <p>Cycle limit: {worker.cycle_timeout_seconds} seconds. Pause between cycles: {worker.interval_seconds} seconds.{worker.cycle_deadline?` Current cycle deadline: ${new Date(worker.cycle_deadline).toLocaleTimeString()}.`:""}</p>
      </li>)}</ul></details>:null}
    </>:null}
  </section>;
}
