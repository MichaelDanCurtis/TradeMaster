"use client";
import { useEffect, useRef, useState } from "react";
import { actOnSchedule, listSchedules, prepareSchedule, readSchedule, schedulerRuntime, readMarketCalendar } from "@/lib/scheduler";
import type { Schedule, ScheduleDetail, ScheduleInput, SchedulerRuntime, MarketCalendar } from "@/lib/scheduler";

type Props={algorithm:string|null;symbol:string;side:string;notional:number;referencePrice:number;protectiveInputs:boolean};
const date=(value:string)=>new Date(value).toLocaleString();
const usd=(value:string)=>Number(value).toLocaleString("en-US",{style:"currency",currency:"USD"});
const terminal=new Set(["completed","stopped","expired","finished_partial"]);

export function ExecutionScheduler({algorithm,symbol,side,notional,referencePrice,protectiveInputs}:Props){
  const [count,setCount]=useState(4),[duration,setDuration]=useState(30),[lead,setLead]=useState(3),[span,setSpan]=useState(10);
  const [calendar,setCalendar]=useState<MarketCalendar|null>(null),[calendarError,setCalendarError]=useState<string|null>(null);
  const [calendarBusy,setCalendarBusy]=useState(false),[startTime,setStartTime]=useState("");
  const [runtime,setRuntime]=useState<SchedulerRuntime|null>(null),[rows,setRows]=useState<Schedule[]>([]);
  const [selected,setSelected]=useState(""),[detail,setDetail]=useState<ScheduleDetail|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState<string|null>(null),[loadError,setLoadError]=useState<string|null>(null);
  const [reviewed,setReviewed]=useState(false);
  const pending=useRef<ScheduleInput|null>(null);
  const mounted=useRef(true);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
  useEffect(()=>{pending.current=null;setReviewed(false);},[algorithm,symbol,side,notional,referencePrice,count,duration,lead,span,protectiveInputs,startTime]);
  useEffect(()=>{
    if(busy)return;
    let active=true,refreshing=false;
    const refresh=async()=>{
      if(refreshing)return;refreshing=true;
      try{
        const [status,catalog,current]=await Promise.all([schedulerRuntime(),listSchedules(),selected?readSchedule(selected):Promise.resolve(null)]);
        if(!active)return;
        setRuntime(status);setRows(catalog.schedules);setLoadError(null);
        if(current)setDetail(current);
      }catch(caught){if(active){setLoadError(caught instanceof Error?caught.message:"Scheduler unavailable");setRuntime(null);}}finally{refreshing=false;}
    };
    void refresh();const timer=window.setInterval(()=>void refresh(),3000);
    return()=>{active=false;window.clearInterval(timer);};
  },[selected,busy]);
  const supported=algorithm!=null&&Object.hasOwn(runtime?.capabilities??{},algorithm);
  const schedule=detail?.schedule;
  async function loadCalendar(){
    setCalendarBusy(true);setCalendarError(null);
    try{const result=await readMarketCalendar();if(mounted.current)setCalendar(result);}
    catch(caught){if(mounted.current){setCalendar(null);setCalendarError(caught instanceof Error?caught.message:"Exchange calendar unavailable");}}
    finally{if(mounted.current)setCalendarBusy(false);}
  }
  async function prepare(){
    if(!algorithm||busy)return;
    setBusy(true);setError(null);setReviewed(false);
    try{
      pending.current??={idempotency_key:crypto.randomUUID(),algorithm,symbol,side,notional_usd:String(notional),limit_price_usd:String(referencePrice),
        count,duration_minutes:duration,span_percent:String(span),start_at:startTime?new Date(startTime).toISOString():new Date(Date.now()+lead*60000).toISOString()};
      const result=await prepareSchedule(pending.current);
      if(!mounted.current)return;
      pending.current=null;setDetail(result);setSelected(result.schedule.schedule_id);
    }catch(caught){if(mounted.current)setError(caught instanceof Error?caught.message:"Could not prepare schedule");}
    finally{if(mounted.current)setBusy(false);}
  }
  async function action(kind:"approve"|"pause"|"resume"|"stop"){
    if(!schedule||busy)return;
    setBusy(true);setError(null);
    try{const result=await actOnSchedule(schedule,kind);if(mounted.current){setDetail(result);setReviewed(false);}}
    catch(caught){if(mounted.current)setError(caught instanceof Error?caught.message:"Schedule action failed");}
    finally{if(mounted.current)setBusy(false);}
  }
  const expired=!!schedule&&Date.now()>=Date.parse(schedule.review_expires_at);
  return <section className="paper-accounting-card execution-scheduler" id="execution-scheduler" aria-label="Paper execution scheduler" aria-busy={busy}>
    <h2>Paper execution scheduler</h2>
    <p role="status">{runtime?.message??"Scheduler status unavailable"}</p>
    {!!runtime?.workers.length&&<p className="muted">Last heartbeat: {date(runtime.workers[0].last_seen_at)} · last cycle: {runtime.workers[0].result.status??runtime.workers[0].state}</p>}
    <p>TWAP releases fixed-limit orders at scheduled times. DCA submits the reviewed limit ladder; the broker waits for those prices. The worker requests cancellation at each deadline. No repricing, market fallback, or catch-up burst.</p>
    <p>Keep this computer and the scheduler worker running. Broker orders remain working during sleep or an outage; deadline cancellation resumes when the worker reconnects.</p>
    <p>Every broker schedule must fit one verified regular market session and end at least one minute before close. Calendar and clock are checked again before approval and each new submission. Closures never shift approved times automatically.</p>
    <button className="secondary-button" disabled={calendarBusy||busy} onClick={()=>void loadCalendar()}>Read exchange sessions</button>
    {calendarError&&<p role="alert" className="error">{calendarError}</p>}
    {calendar&&<div aria-label="Broker exchange calendar"><p>Broker clock: {date(calendar.clock_at)} · market {calendar.is_open?"open":"closed"} · next open {date(calendar.next_open)}. Times shown in your local timezone.</p>
      <ul>{calendar.sessions.map(session=><li key={session.session_date}>{session.session_date}: {date(session.opens_at)} – {date(session.closes_at)}</li>)}</ul>
      <p>Observed {date(calendar.observed_at)}. Refreshing this list does not change any order or schedule.</p></div>}
    {!supported&&<p>Select TWAP or Dollar-cost rungs to prepare a schedule. Other algorithms remain analytical previews.</p>}
    {supported&&<>
      <p>Prepare {symbol} {side} from the budget and manual reference price above. The reference becomes your exact price limit. Protective stop/take-profit inputs belong to the separate manual ticket.</p>
      {protectiveInputs&&<p role="alert">Clear the manual protective inputs before preparing a schedule; this scheduler does not attach protective children.</p>}
      <fieldset disabled={busy} className="scheduler-inputs"><legend>Schedule terms</legend>
        <label>Slices / rungs<input aria-label="Schedule slice count" type="number" min="2" max="12" value={count} onChange={e=>setCount(Number(e.target.value))}/></label>
        <label>Duration (minutes)<input aria-label="Schedule duration minutes" type="number" min="1" max="390" value={duration} onChange={e=>setDuration(Number(e.target.value))}/></label>
        <label>Exact start (local time, optional)<input aria-label="Schedule exact local start" type="datetime-local" value={startTime} onChange={e=>setStartTime(e.target.value)}/></label>
        <label>Start in (minutes)<input aria-label="Schedule start delay minutes" type="number" min="1" max="10080" disabled={!!startTime} value={lead} onChange={e=>setLead(Number(e.target.value))}/></label>
        {algorithm==="dca_ladder"&&<label>Ladder span (%)<input aria-label="Schedule ladder span percent" type="number" min="0.01" max="50" step="0.01" value={span} onChange={e=>setSpan(Number(e.target.value))}/></label>}
      </fieldset>
      <button className="secondary-button" onClick={()=>void prepare()} disabled={busy||protectiveInputs}>Prepare schedule for review</button>
    </>}
    {error&&<p className="error" role="alert">{error}</p>}{loadError&&<p className="error" role="alert">{loadError}</p>}
    <label>Saved schedules<select aria-label="Saved execution schedules" value={selected} disabled={busy} onChange={e=>{setSelected(e.target.value);setDetail(null);setReviewed(false);}}>
      <option value="">Select a saved schedule</option>
      {rows.map(row=><option key={row.schedule_id} value={row.schedule_id}>{row.payload.request.symbol} · {row.payload.request.algorithm} · {row.state.replaceAll("_"," ")} · {date(row.payload.request.start_at)}</option>)}
      {schedule&&!rows.some(row=>row.schedule_id===schedule.schedule_id)&&<option value={schedule.schedule_id}>{schedule.payload.request.symbol} · {schedule.state}</option>}
    </select></label>
    {detail&&schedule&&<div aria-label="Exact schedule review">
      <h3>{schedule.payload.request.symbol} · {schedule.payload.request.algorithm} · {schedule.state.replaceAll("_"," ")}</h3>
      <p>{schedule.message}</p>
      <p>{schedule.payload.evidence_kind==="fixture"?"Fixture simulation":"Broker paper account"} · {schedule.payload.account_id}</p>
      {schedule.payload.market_session&&<p>Verified session: {date(schedule.payload.market_session.opens_at)} – {date(schedule.payload.market_session.closes_at)}.</p>}
      <p>Maximum order notional: {usd(schedule.payload.maximum_notional_usd)} · unused budget: {usd(schedule.payload.unused_budget_usd)} · ends {date(schedule.payload.ends_at)}</p>
      <div className="paper-accounting-table"><table><thead><tr><th>Leg</th><th>Side</th><th>Shares</th><th>Limit</th><th>Release</th><th>Deadline</th><th>State</th><th>Filled</th><th>Avg fill</th></tr></thead>
        <tbody>{detail.legs.map(leg=><tr key={leg.leg_id}><td>{leg.ordinal}</td><td>{leg.order.order.side}</td><td>{leg.order.order.quantity}</td><td>{usd(leg.order.order.limit_price_usd)}</td><td>{date(leg.due_at)}</td><td>{date(leg.expires_at)}</td><td>{leg.order.state.replaceAll("_"," ")}</td><td>{leg.attempt?.filled_quantity??"0"}</td><td>{leg.attempt?.observation?.average_fill_price_usd?usd(leg.attempt.observation.average_fill_price_usd):"—"}</td></tr>)}</tbody></table></div>
      <ul>{schedule.payload.notes.map(note=><li key={note}>{note}</li>)}</ul>
      <p>Orders already claimed for submission can still reach the broker after Pause or Stop. Stop remains pending until cancellation or a terminal broker receipt is confirmed. Fills already executed cannot be undone.</p>
      {schedule.state==="previewed"&&<>
        <p>Review expires {date(schedule.review_expires_at)}.{expired?" Prepare a new schedule to refresh the deadline.":""}</p>
        <label><input type="checkbox" checked={reviewed} disabled={busy||expired} onChange={e=>setReviewed(e.target.checked)}/>I reviewed every listed order and authorize automatic paper submission within these exact terms.</label>
        <button className="primary-button" onClick={()=>void action("approve")} disabled={busy||!reviewed||expired||!runtime?.connected}>Approve listed orders and start schedule</button>
      </>}
      <div className="paper-accounting-actions">
        {schedule.state==="active"&&<button className="secondary-button" disabled={busy} onClick={()=>void action("pause")}>Pause new submissions</button>}
        {schedule.state==="paused"&&<button className="secondary-button" disabled={busy||!runtime?.connected} onClick={()=>void action("resume")}>Resume original schedule</button>}
        {!terminal.has(schedule.state)&&schedule.state!=="stopping"&&<button className="secondary-button" disabled={busy} onClick={()=>void action("stop")}>Stop and cancel outstanding orders</button>}
      </div>
      <details><summary>Schedule history ({detail.events.length})</summary><ul>{detail.events.map(event=><li key={event.event_id}>{date(event.created_at)} · {event.kind.replaceAll("_"," ")}</li>)}</ul></details>
    </div>}
  </section>;
}
