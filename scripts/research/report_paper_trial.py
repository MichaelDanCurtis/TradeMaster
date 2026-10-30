"""Read-only five-session report from preserved broker accounting and order receipts."""
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tradingagents.research.accounting_storage import decode_report

TERMINAL={'filled','canceled','expired','rejected'}

def instant(value):
    value=datetime.fromisoformat(value)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def session_evidence(sessions, observations, now):
    result=[]
    for session in sessions:
        opening,closing=instant(session['opens_at']),instant(session['closes_at'])
        usable=[r for r in observations if r['report'].get('reconciled') and r['report'].get('evidence_kind')=='broker_paper' and instant(r['observed_at'])<=now]
        at_open=[r for r in usable if opening-timedelta(minutes=15)<=instant(r['observed_at'])<=opening+timedelta(minutes=15)]
        at_close=[r for r in usable if closing<=instant(r['observed_at'])<=closing+timedelta(minutes=30)]
        # Future rows can never establish an elapsed trading session.
        state='pending' if now<closing else 'observed' if at_open and at_close else 'missing_observations'
        result.append({**session,'state':state,'opening_receipt':at_open[-1]['reconciliation_id'] if at_open else None,
            'closing_receipt':at_close[0]['reconciliation_id'] if at_close else None})
    return result


def trial_metrics(report, owners, now):
    """Dollar P&L/drawdown of schedule-owned lots, without inventing funding."""
    result={'status':'unavailable','reason':'account_not_reconciled','pnl_usd':None,
        'fees_usd':None,'income_usd':None,'current_drawdown_usd':None,'maximum_drawdown_usd':None,
        'drawdown_fraction':None,'equity_series':[]}
    if not report.get('reconciled') or report.get('discrepancies'): return result
    attributed=[a for a in report.get('attribution',[]) if a['owner'] in owners]
    if not attributed:
        result.update(status='no_attributed_activity',reason='no_trial_lots_or_income_observed')
        return result
    series=[];known=set();high=Decimal(0);maximum=Decimal(0);previous=None
    try:
        for point in report.get('owner_equity_history',[]):
            at=instant(point['observed_at'])
            if at>now or (previous is not None and at<=previous): raise ValueError('invalid_observation_sequence')
            previous=at;total=Decimal(0)
            for owner in owners:
                value=point['owners'].get(owner)
                if value is None:
                    if owner in known: raise ValueError('owner_disappeared_from_history')
                    continue
                known.add(owner)
                if value.get('marks_complete') is not True or value.get('equity_without_allocations_usd') is None:
                    raise ValueError('missing_trial_valuation')
                amount=Decimal(value['equity_without_allocations_usd'])
                if not amount.is_finite(): raise ValueError('invalid_trial_valuation')
                total+=amount
            high=max(high,total);drawdown=high-total;maximum=max(maximum,drawdown)
            series.append({'observed_at':point['observed_at'],'pnl_usd':str(total),'drawdown_usd':str(drawdown)})
        if not series or not known: raise ValueError('missing_trial_history')
        def total(field):
            value=sum((Decimal(a[field]) for a in attributed),Decimal(0))
            if not value.is_finite(): raise ValueError('invalid_trial_total')
            return value
        pnl=total('period_pnl_usd')
        if abs(Decimal(series[-1]['pnl_usd'])-pnl)>Decimal('0.000001'):
            raise ValueError('trial_pnl_does_not_reconcile_to_owner_history')
        result.update(status='observed',reason=None,pnl_usd=str(pnl),fees_usd=str(total('fees_usd')),
            income_usd=str(total('income_usd')),current_drawdown_usd=series[-1]['drawdown_usd'],
            maximum_drawdown_usd=str(maximum),equity_series=series)
    except (KeyError,ValueError,InvalidOperation,TypeError) as exc:
        result['reason']=str(exc) if isinstance(exc,ValueError) else 'invalid_trial_history'
    return result


def verified_terminal(order, now):
    """Require the dispatch-used exact approval and its matching native receipt."""
    from tradingagents.research.execution_contracts import PaperOrderObservation
    attempt=order.get('broker_receipt');approval=order.get('approval_receipt')
    if not attempt or not approval or attempt['state'] not in TERMINAL: return False
    try:
        after=approval['after_payload']
        observation=PaperOrderObservation.model_validate(attempt['observation'])
        return bool(approval['action']=='approve_order' and approval['approval_id']==attempt['approval_id']
            and approval['intent_id']==order['intent_id'] and after['order_hash']==order['content_hash']
            and after['exact_order']==order['terms'] and order['local_state']==attempt['state']==observation.status
            and observation.client_order_id==attempt['client_order_id'] and observation.broker_order_id==attempt['broker_order_id']
            and observation.symbol==order['terms']['symbol'] and observation.side==order['terms']['side']
            and observation.quantity==order['terms']['quantity'] and observation.filled_quantity==Decimal(attempt['filled_quantity'])
            and instant(approval['created_at'])<=instant(attempt['created_at'])<=observation.observed_at<=now)
    except (KeyError,ValueError,InvalidOperation,TypeError): return False


def dollars(value):
    return 'unavailable' if value is None else f'{value} USD'


def execution_accounting_check(orders, latest, account_key, baseline_id, now):
    """Join native terminal receipts to the independently reconciled fill ledger."""
    checks=[]
    ledger=latest['report'] if latest else {}
    for order in orders:
        item={'order_id':order['order_id'],'state':'pending','issues':[],
            'broker_filled_quantity':None,'ledger_filled_quantity':None,
            'ledger_fees_usd':None,'source_ids':[]}
        checks.append(item)
        if not order.get('broker_receipt') and order['local_state'] in TERMINAL:
            item.update(state='local_only',issues=['local_disposition_is_not_broker_lifecycle_evidence']); continue
        if not verified_terminal(order,now):
            item['issues']=['verified_terminal_receipt_unavailable']; continue
        receipt=order['broker_receipt'];observation=receipt['observation']
        item['broker_filled_quantity']=str(receipt['filled_quantity'])
        if not latest or instant(latest['observed_at'])<instant(observation['observed_at']):
            item['issues']=['reconciliation_after_terminal_receipt_required']; continue
        if (ledger.get('evidence_kind')!='broker_paper' or ledger.get('account_key')!=account_key
                or ledger.get('baseline_id')!=baseline_id or not ledger.get('reconciled')
                or ledger.get('discrepancies')):
            item.update(state='mismatch',issues=['reconciled_paper_account_identity_required']); continue
        try:
            fills=[f for f in ledger.get('fills',[]) if f.get('broker_order_id')==receipt['broker_order_id']]
            ids=[f['source_id'] for f in fills]
            if len(set(ids))!=len(ids): raise ValueError('duplicate_fill_source_ids')
            quantity=Decimal(0);gross=Decimal(0);fees=Decimal(0)
            for fill in fills:
                q=Decimal(fill['quantity']);price=Decimal(fill['price_usd']);fee=Decimal(fill['fee_usd'])
                if not all(v.is_finite() for v in (q,price,fee)) or q<=0 or price<=0 or fee<0:
                    raise ValueError('invalid_fill_amount')
                if (fill['symbol']!=order['terms']['symbol'] or fill['side']!=order['terms']['side']
                        or fill['executor']!='schedule:'+order['schedule_id']):
                    raise ValueError('fill_identity_or_trial_owner_mismatch')
                if instant(fill['effective_at'])>instant(observation['observed_at']):
                    raise ValueError('fill_after_terminal_observation')
                quantity+=q;gross+=q*price;fees+=fee
            item.update(ledger_filled_quantity=str(quantity),ledger_fees_usd=str(fees),source_ids=ids)
            if quantity!=Decimal(receipt['filled_quantity']): raise ValueError('broker_and_ledger_fill_quantity_mismatch')
            # Native average prices may be rounded to four decimal places.
            # This tolerance is per share; quantities must match exactly.
            if quantity and abs(gross/quantity-Decimal(observation['average_fill_price_usd']))>Decimal('0.0001'):
                raise ValueError('broker_and_ledger_average_price_mismatch')
            item['state']='matched'
        except (KeyError,ValueError,InvalidOperation,TypeError) as exc:
            item.update(state='mismatch',issues=[str(exc) if isinstance(exc,ValueError) else 'invalid_fill_ledger'])
    return {'complete':any(c['state']=='matched' for c in checks) and all(c['state'] in {'matched','local_only'} for c in checks),
        'average_price_tolerance_usd_per_share':'0.0001','orders':checks}



def research_readiness(plan_path, plan):
    """Refresh source facts from verified capture bytes, never from a UI flag."""
    from scripts.research.review_paper_trial_data import build_review
    from tradingagents.research.contracts import content_hash
    try:
        review=build_review(Path(plan_path).parent)
        if review['criteria_hash']!=plan.get('criteria_hash'):
            raise ValueError('Trial criteria and source review differ')
        return {'state':review['readiness'],'checked_at':review['reviewed_at'],
            'criteria_hash':review['criteria_hash'],'review_hash':content_hash(review),
            'calendar_sessions':review['calendar_sessions'],
            'bars_per_feed':{k:v['source_rows'] for k,v in review['feeds'].items()},
            'historical_windows':review['historical_windows'],
            'dividends_missing_currency':review['corporate_actions']['dividends_missing_currency'],
            'known_effective_window_omissions':len(review['action_effective_window_review']['missing_from_original']) if review['action_effective_window_review'] else None,
            'remaining':review['remaining'],
            'scope':'Source readiness for the frozen trial criteria. Counts do not establish historical availability or strategy qualification.'}
    except (ValueError,KeyError,TypeError,OSError,AssertionError):
        return {'state':'unavailable','remaining':['Source review could not be verified against this trial plan and its preserved captures.'],
                'scope':'No research readiness or qualification is inferred from missing or inconsistent evidence.'}


def build_report(plan_path, database):
    plan=json.loads(Path(plan_path).read_text())
    db=sqlite3.connect(f'file:{Path(database).resolve()}?mode=ro',uri=True);db.row_factory=sqlite3.Row
    db.execute("BEGIN")
    try:
        now=datetime.now(timezone.utc)
        enrollment=db.execute('SELECT * FROM paper_account_enrollments WHERE account_key=?',(plan['account_key'],)).fetchone()
        if enrollment is None or enrollment['baseline_id']!=plan['baseline_id']:raise ValueError('Trial baseline changed or is unavailable')
        observations=[]
        # Historical reports contain cumulative curves; loading every full report
        # is quadratic. Session evidence needs only two flags and source identity.
        for row in db.execute("SELECT reconciliation_id, observed_at, json_extract(report, '$.reconciled') AS reconciled, json_extract(report, '$.evidence_kind') AS evidence_kind FROM paper_account_reconciliations WHERE account_key=? ORDER BY observed_at",(plan['account_key'],)):
            item=dict(row);item['report']={'reconciled':bool(item.pop('reconciled')),'evidence_kind':item.pop('evidence_kind')}
            if instant(item['observed_at'])<=now: observations.append(item)
        latest=dict(observations[-1]) if observations else None
        if latest:
            latest['report']=decode_report(json.loads(db.execute('SELECT report FROM paper_account_reconciliations WHERE reconciliation_id=?',(latest['reconciliation_id'],)).fetchone()['report']))
        schedule_rows=[];attempts=[]
        for identifier in plan['schedule_ids']:
            row=db.execute('SELECT * FROM execution_schedules WHERE schedule_id=?',(identifier,)).fetchone()
            if row is None or row['account_key']!=plan['account_key']:raise ValueError('Trial schedule identity mismatch')
            schedule_rows.append({'schedule_id':identifier,'state':row['state'],'approved_at':row['approved_at'],
                'review_expires_at':row['review_expires_at'],'review_expired':now>=instant(row['review_expires_at'])})
            for leg in db.execute('SELECT * FROM execution_schedule_legs WHERE schedule_id=? ORDER BY ordinal',(identifier,)):
                order=dict(db.execute('SELECT * FROM paper_exact_orders WHERE order_id=?',(leg['order_id'],)).fetchone())
                attempt=db.execute('SELECT * FROM paper_execution_attempts WHERE order_id=?',(leg['order_id'],)).fetchone()
                receipt=dict(attempt) if attempt else None
                approval=None
                if receipt:
                    receipt['observation']=json.loads(receipt['observation']) if receipt['observation'] else None
                    row=db.execute('SELECT * FROM ui_approvals WHERE approval_id=?',(receipt['approval_id'],)).fetchone()
                    if row:
                        approval=dict(row);approval['after_payload']=json.loads(approval['after_payload'])
                attempts.append({'order_id':leg['order_id'],'schedule_id':identifier,'intent_id':order['intent_id'],'content_hash':order['content_hash'],
                    'terms':json.loads(order['order']),'local_state':order['state'],
                    'broker_receipt':receipt,'approval_receipt':approval})
    finally:
        db.close()
    report=latest['report'] if latest else {}
    owners={'schedule:'+identifier for identifier in plan['schedule_ids']}
    attributed=[a for a in report.get('attribution',[]) if a['owner'] in owners]
    omitted=set(report.get('source_corrections',{}).get('excluded_observation_ids',[]))
    usable=[r for r in observations if r['reconciliation_id'] not in omitted]
    session_rows=session_evidence(plan['sessions'],usable,now)
    metrics=trial_metrics(report,owners,now)
    broker_terminal=[a for a in attempts if verified_terminal(a,now)]
    invalid_receipts=[a['order_id'] for a in attempts if a['broker_receipt'] and a['broker_receipt']['state'] in TERMINAL and not verified_terminal(a,now)]
    unfinished=[a for a in attempts if a['local_state'] not in TERMINAL]
    approved=any(s['approved_at'] for s in schedule_rows)
    all_sessions=len(session_rows)==5 and all(s['state']=='observed' for s in session_rows)
    accounting_check=execution_accounting_check(attempts,latest,plan['account_key'],plan['baseline_id'],now)
    accounting_mismatch=any(c['state']=='mismatch' for c in accounting_check['orders'])
    complete=bool(approved and broker_terminal and not unfinished and all_sessions and report.get('reconciled') and not report.get('discrepancies') and not invalid_receipts and metrics['status']!='unavailable' and accounting_check['complete'])
    summary={'generated_at':now.isoformat(),'operational_evidence_complete':complete,'research_validated':False,
        'research_data_readiness':research_readiness(plan_path,plan),
        'recommendation':'revise' if report.get('discrepancies') or invalid_receipts or accounting_mismatch else 'continue_testing','baseline_id':plan['baseline_id'],'proposed_allocation_usd':plan['proposed_allocation_usd'],
        'sessions':session_rows,'schedules':schedule_rows,'orders':attempts,'latest_reconciliation_id':latest['reconciliation_id'] if latest else None,
        'account_reconciled':report.get('reconciled',False),'discrepancies':report.get('discrepancies',[]),
        'trial_attribution':attributed if metrics['status']=='observed' else [],'trial_metrics':metrics,
        'trial_pnl_usd':metrics['pnl_usd'],'invalid_terminal_receipts':invalid_receipts,
        'execution_accounting_check':accounting_check,
        'account_drawdown_fraction':report.get('drawdown_fraction'),'account_max_drawdown_fraction':report.get('maximum_drawdown_fraction'),
        'limitations':['No order receipt is inferred from a preview or local cancellation',
            'Trial performance uses only schedule-owned lots; opening and unrelated holdings are excluded',
            'Absent trial fills do not establish a measured strategy return',
            'Dividend ex-dates and payment dates may straddle the trial; income requires broker activity and unpaid entitlements are not inferred',
            'Trial drawdown is observed peak-to-trough dollar P&L; no funded capital denominator or percentage return is invented',
            'Five sessions do not establish statistical profitability',
            'Research data admission and prospective strategy evaluation remain separate requirements']}
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,default=Path('.research-artifacts/paper-trial/trial-plan.json'))
    parser.add_argument('--database',type=Path,default=Path('.tradingagents-ui.db'))
    parser.add_argument('--output',type=Path,default=Path('docs/PAPER_TRIAL_PROGRESS.md'))
    args=parser.parse_args()
    summary=build_report(args.plan,args.database)
    complete=summary['operational_evidence_complete'];metrics=summary['trial_metrics']
    session_rows=summary['sessions'];attempts=summary['orders'];invalid_receipts=summary['invalid_terminal_receipts']
    broker_terminal=[a for a in attempts if verified_terminal(a,instant(summary['generated_at']))]
    args.output.with_suffix('.json').write_text(json.dumps(summary,indent=2))
    lines=['# Alpaca paper trial progress','',f'Generated: {summary["generated_at"]}',
        '',f'Operational evidence complete: **{complete}**. Research validated: **False**.',
        '',f'Recommendation: **{summary["recommendation"].replace("_"," ")}**. Broker-terminal trial orders: {len(broker_terminal)}. Account reconciled: {summary["account_reconciled"]}.',
        '', '| Session | Evidence |','| --- | --- |']
    lines += [f'| {r["session_date"]} | {r["state"]} |' for r in session_rows]
    lines += ['',f'Trial-attributed P&L: {summary["trial_pnl_usd"] if summary["trial_pnl_usd"] is not None else "unavailable: "+metrics["reason"]}.',
        f'Trial observed drawdown: {dollars(metrics["current_drawdown_usd"])} current; {dollars(metrics["maximum_drawdown_usd"])} maximum. Percentage: unavailable without approved funding.',
        f'Trial recorded fees: {dollars(metrics["fees_usd"])}; income: {dollars(metrics["income_usd"])}.',
        '', '## Order evidence','', '| Order | Local status | Broker status | Broker order ID | Filled shares |',
        '| --- | --- | --- | --- | --- |']
    lines += [f'| {a["order_id"]} | {a["local_state"]} | {(a["broker_receipt"] or {}).get("state","no submission")} | {(a["broker_receipt"] or {}).get("broker_order_id") or "none"} | {(a["broker_receipt"] or {}).get("filled_quantity","not observed")} |' for a in attempts]
    lines += [ '', '## Reconciliation','', f'Discrepancies: {json.dumps(summary["discrepancies"])}. Invalid terminal receipts: {json.dumps(invalid_receipts)}.',
        '', 'Each terminal broker receipt must match a subsequent reconciled paper-account fill ledger. Quantities match exactly; average fill prices allow $0.0001 per share for native rounding.',
        '', '| Order | Broker/ledger check | Details |', '| --- | --- | --- |']
    lines += [f'| {c["order_id"]} | {c["state"]} | {", ".join(c["issues"]) or "Filled quantity, price and schedule ownership match"} |' for c in summary['execution_accounting_check']['orders']]
    research=summary['research_data_readiness']
    lines += ['', '## Research source readiness', '', research['state'], '', research['scope']]
    if research.get('bars_per_feed'):
        lines += ['', f"Calendar sessions: {research['calendar_sessions']}. Captured bars: {json.dumps(research['bars_per_feed'])}.", f"Criteria: {research['criteria_hash']}. Review: {research['review_hash']}."]
    lines += ['', *['- '+gap for gap in research['remaining']]]
    lines += [
        '', 'The proposed allocation is $1,000. Schedule approval remains separate; no execution is triggered by this report.',
        '', '## Limitations',''] + ['- '+v for v in summary['limitations']]
    args.output.write_text('\n'.join(lines)+'\n')
    print(json.dumps({'report':str(args.output),'complete':complete,'broker_terminal_orders':len(broker_terminal),'session_states':[r['state'] for r in session_rows]}))

if __name__=='__main__':main()
