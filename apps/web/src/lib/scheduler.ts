import { apiBase } from "./api";

export type Schedule = {
  schedule_id:string; content_hash:string; revision:number; state:string; message:string; review_expires_at:string;
  payload:{request:{algorithm:string;symbol:string;side:string;start_at:string};account_id:string;provider_id:string;evidence_kind:string;
    market_session?:MarketSession|null;maximum_notional_usd:string;unused_budget_usd:string;ends_at:string;notes:string[]};
};
export type ScheduleDetail = {schedule:Schedule;events:{event_id:string;kind:string;created_at:string;payload:Record<string,unknown>}[];
  legs:{leg_id:string;ordinal:number;due_at:string;expires_at:string;order:{order_id:string;state:string;order:{symbol:string;side:string;quantity:number;limit_price_usd:string;expires_at:string}};
    attempt:{state:string;filled_quantity:string;observation:{average_fill_price_usd?:string|null}|null;failure_reason:string|null}|null}[]};
export type SchedulerRuntime = {connected:boolean;message:string;capabilities:Record<string,string>;workers:{worker_id:string;last_seen_at:string;state:string;result:{status?:string}}[]};
export type ScheduleInput = {idempotency_key:string;algorithm:string;symbol:string;side:string;notional_usd:string;limit_price_usd:string;
  count:number;duration_minutes:number;span_percent:string;start_at:string};
async function call<T>(path:string, body?:unknown):Promise<T>{
  const response=await fetch(`${apiBase()}/api/execution-schedules${path}`,{method:body===undefined?"GET":"POST",cache:"no-store",
    headers:{"Content-Type":"application/json","x-trademaster-room":"market"},body:body===undefined?undefined:JSON.stringify(body)});
  if(!response.ok){let message=`Schedule request failed (${response.status})`;try{const payload=await response.json();if(typeof payload.detail==="string")message=payload.detail;else if(Array.isArray(payload.detail))message=payload.detail.map((item:{msg?:string})=>item.msg??"Invalid field").join("; ");}catch{}throw new Error(message);}
  return response.json() as Promise<T>;
}
export const schedulerRuntime=()=>call<SchedulerRuntime>("/runtime");
export const listSchedules=()=>call<{schedules:Schedule[]}>("");
export const readSchedule=(id:string)=>call<ScheduleDetail>(`/${encodeURIComponent(id)}`);
export const prepareSchedule=(input:ScheduleInput)=>call<ScheduleDetail>("",input);
export const actOnSchedule=(schedule:Schedule,action:"approve"|"pause"|"resume"|"stop")=>call<ScheduleDetail>(`/${encodeURIComponent(schedule.schedule_id)}/actions`,{
  action,expected_hash:schedule.content_hash,expected_revision:schedule.revision,actor:"local-user"});

export type MarketSession={session_date:string;opens_at:string;closes_at:string};
export type MarketCalendar={observed_at:string;clock_at:string;is_open:boolean;next_open:string;next_close:string;sessions:MarketSession[]};
export const readMarketCalendar=()=>call<MarketCalendar>("/calendar");
