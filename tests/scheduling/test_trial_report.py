import importlib.util
from datetime import datetime, timezone
from pathlib import Path

spec=importlib.util.spec_from_file_location('trial_report',Path(__file__).resolve().parents[2]/'scripts/research/report_paper_trial.py')
report=importlib.util.module_from_spec(spec);spec.loader.exec_module(report)

def test_sessions_require_elapsed_time_and_real_reconciled_open_and_close_observations():
    sessions=[{'session_date':'2026-09-08','opens_at':'2026-09-08T13:30:00Z','closes_at':'2026-09-08T20:00:00Z'}]
    def row(at,ok=True,kind='broker_paper'):
        return {'reconciliation_id':at,'observed_at':at,'report':{'reconciled':ok,'evidence_kind':kind}}
    rows=[row('2026-09-08T13:31:00Z'),row('2026-09-08T20:01:00Z')]
    before=datetime(2026,9,8,19,tzinfo=timezone.utc);after=datetime(2026,9,8,21,tzinfo=timezone.utc)
    assert report.session_evidence(sessions,rows,before)[0]['state']=='pending'
    assert report.session_evidence(sessions,rows,after)[0]['state']=='observed'
    for invalid in [[],rows[:1],[rows[0],row('2026-09-08T20:01:00Z',False)],
                    [rows[0],row('2026-09-08T20:01:00Z',kind='fixture')],
                    [rows[0],row('2026-09-08T20:31:00Z')]]:
        assert report.session_evidence(sessions,invalid,after)[0]['state']=='missing_observations'


def accounting_report():
    owner='schedule:trial'
    rows=[]
    for index,pnl in enumerate(['0','-1','10','4']):
        rows.append({'observed_at':f'2026-09-08T14:0{index}:00Z','owners':{
            owner:{'marks_complete':True,'equity_without_allocations_usd':pnl},
            'legacy_manual':{'marks_complete':True,'equity_without_allocations_usd':'90000'},
            'external_manual':{'marks_complete':True,'equity_without_allocations_usd':'-5000'}}})
    return {'reconciled':True,'discrepancies':[],'owner_equity_history':rows,
        'attribution':[{'owner':owner,'period_pnl_usd':'4','fees_usd':'1','income_usd':'2'},
            {'owner':'legacy_manual','period_pnl_usd':'10000','fees_usd':'0','income_usd':'500'}]}


def test_trial_dollar_drawdown_excludes_other_holdings_and_never_invents_percentage():
    now=datetime(2026,9,8,21,tzinfo=timezone.utc)
    metrics=report.trial_metrics(accounting_report(),{'schedule:trial'},now)
    assert metrics['status']=='observed'
    assert (metrics['pnl_usd'],metrics['fees_usd'],metrics['income_usd'])==('4','1','2')
    assert metrics['current_drawdown_usd']==metrics['maximum_drawdown_usd']=='6'
    assert metrics['drawdown_fraction'] is None


def test_uncertain_marks_reconciliation_or_history_suppress_trial_metrics():
    import copy
    base=accounting_report();now=datetime(2026,9,8,21,tzinfo=timezone.utc)
    cases=[]
    row=copy.deepcopy(base);row['reconciled']=False;cases.append(row)
    row=copy.deepcopy(base);row['discrepancies']=[{'code':'cash_mismatch'}];cases.append(row)
    row=copy.deepcopy(base);row['owner_equity_history'][2]['owners']['schedule:trial']['marks_complete']=False;cases.append(row)
    row=copy.deepcopy(base);del row['owner_equity_history'][2]['owners']['schedule:trial'];cases.append(row)
    row=copy.deepcopy(base);row['attribution'][0]['period_pnl_usd']='100';cases.append(row)
    row=copy.deepcopy(base);row['owner_equity_history'][-1]['observed_at']='2026-09-09T14:00:00Z';cases.append(row)
    for row in cases:
        metrics=report.trial_metrics(row,{'schedule:trial'},now)
        assert metrics['status']=='unavailable' and metrics['pnl_usd'] is None and not metrics['equity_series']


def test_no_attributed_activity_remains_unmeasured():
    row=accounting_report();row['attribution']=row['attribution'][1:]
    metrics=report.trial_metrics(row,{'schedule:trial'},datetime(2026,9,8,21,tzinfo=timezone.utc))
    assert metrics['status']=='no_attributed_activity' and metrics['pnl_usd'] is None


def test_trial_metrics_consume_accounting_ledger_with_shared_symbol_opening_lots():
    from datetime import timedelta
    from decimal import Decimal as D
    from tradingagents.research.accounting import reconcile_account
    from tradingagents.research.accounting_contracts import AccountActivity
    from tradingagents.research.execution_contracts import AccountPosition, PaperAccountSnapshot

    start=datetime(2026,9,8,13,30,tzinfo=timezone.utc)
    def snapshot(second,cash,quantity,basis,value):
        return PaperAccountSnapshot(provider_id='fixture',account_id='account',evidence_kind='fixture',
            started_at=start+timedelta(seconds=second),observed_at=start+timedelta(seconds=second),
            cash_usd=cash,equity_usd=D(cash)+D(value),buying_power_usd=cash,daily_turnover_usd=0,
            trading_blocked=False,drawdown_fraction=None,complete=True,open_orders=[],positions=[AccountPosition(
                symbol='NVDA',quantity=quantity,cost_basis_usd=basis,market_value_usd=value)])
    baseline=snapshot(0,'9000',10,'1000','2000')
    fill=AccountActivity(source_id='trial-fill',effective_at=start+timedelta(seconds=1),kind='fill',
        symbol='NVDA',side='buy',quantity=1,price_usd=200,fee_usd=1,broker_order_id='trial-order')
    ledger=reconcile_account(baseline,[snapshot(2,'8799',11,'1200','2200'),
        snapshot(3,'8799',11,'1200','2310')],[fill],{'trial-order':'schedule:trial'})
    assert ledger['reconciled'],ledger['discrepancies']
    assert ledger['investment_pnl_usd']==D('109')
    metrics=report.trial_metrics(ledger,{'schedule:trial'},start+timedelta(seconds=4))
    assert metrics['status']=='observed',metrics
    assert D(metrics['pnl_usd'])==D('9')  # The other $100 belongs to opening holdings.
    assert D(metrics['fees_usd'])==D('1')
    assert D(metrics['maximum_drawdown_usd'])==D('1')
    assert D(metrics['current_drawdown_usd'])==0
    assert metrics['drawdown_fraction'] is None


def terminal_order():
    terms={'symbol':'NVDA','side':'buy','quantity':1,'limit_price_usd':'200.00','time_in_force':'gtc','expires_at':'2026-09-08T13:45:00Z'}
    return {'intent_id':'intent','content_hash':'hash','terms':terms,'local_state':'canceled',
        'approval_receipt':{'approval_id':'approval','action':'approve_order','intent_id':'intent',
            'created_at':'2026-09-08T13:35:00Z','after_payload':{'order_hash':'hash','exact_order':terms}},
        'broker_receipt':{'state':'canceled','approval_id':'approval','client_order_id':'client','broker_order_id':'broker',
            'filled_quantity':'0','created_at':'2026-09-08T13:40:00Z','observation':{'client_order_id':'client',
            'broker_order_id':'broker','symbol':'NVDA','side':'buy','quantity':1,'filled_quantity':'0',
            'average_fill_price_usd':None,'status':'canceled','observed_at':'2026-09-08T13:45:01Z'}}}


def test_terminal_receipt_requires_exact_dispatch_used_approval_and_broker_identity():
    import copy
    now=datetime(2026,9,8,21,tzinfo=timezone.utc)
    base=terminal_order();assert report.verified_terminal(base,now)
    cases=[]
    row=copy.deepcopy(base);row['approval_receipt']=None;cases.append(row)
    row=copy.deepcopy(base);row['approval_receipt']['after_payload']['order_hash']='other';cases.append(row)
    row=copy.deepcopy(base);row['broker_receipt']['approval_id']='other';cases.append(row)
    row=copy.deepcopy(base);row['broker_receipt']['observation']['symbol']='MSFT';cases.append(row)
    row=copy.deepcopy(base);row['broker_receipt']['observation']['client_order_id']='other';cases.append(row)
    row=copy.deepcopy(base);row['broker_receipt']['observation']['observed_at']='2026-09-09T13:45:01Z';cases.append(row)
    row=copy.deepcopy(base);row['broker_receipt']=None;cases.append(row)
    for row in cases:assert not report.verified_terminal(row,now)


def execution_ledger_case():
    order=terminal_order();order.update(order_id='order',schedule_id='trial')
    order['broker_receipt']['filled_quantity']='0.5'
    order['broker_receipt']['observation'].update(filled_quantity='0.5',average_fill_price_usd='199.5')
    latest={'observed_at':'2026-09-08T13:46:00Z','report':{
        'reconciled':True,'discrepancies':[],'account_key':'account','baseline_id':'baseline','evidence_kind':'broker_paper',
        'fills':[{'source_id':'fill','broker_order_id':'broker','symbol':'NVDA','side':'buy','quantity':'0.5',
            'price_usd':'199.5','fee_usd':'0.01','executor':'schedule:trial','effective_at':'2026-09-08T13:41:00Z'}]}}
    return order,latest


def check_execution(order,latest):
    return report.execution_accounting_check([order],latest,'account','baseline',datetime(2026,9,8,21,tzinfo=timezone.utc))


def test_canceled_partial_fill_requires_matching_account_ledger():
    order,latest=execution_ledger_case()
    result=check_execution(order,latest)
    assert result['complete'] and result['orders'][0]['ledger_filled_quantity']=='0.5'
    assert result['orders'][0]['ledger_fees_usd']=='0.01'
    latest['report']['fills']=[]
    result=check_execution(order,latest)
    assert not result['complete']
    assert result['orders'][0]['issues']==['broker_and_ledger_fill_quantity_mismatch']


def test_terminal_receipt_requires_subsequent_account_observation():
    order,latest=execution_ledger_case();latest['observed_at']='2026-09-08T13:44:00Z'
    result=check_execution(order,latest)
    assert not result['complete'] and result['orders'][0]['state']=='pending'
    assert result['orders'][0]['issues']==['reconciliation_after_terminal_receipt_required']


def test_wrong_account_or_baseline_and_non_broker_ledger_cannot_match():
    for field,value in [('account_key','other'),('baseline_id','other'),('evidence_kind','fixture'),('reconciled',False)]:
        order,latest=execution_ledger_case();latest['report'][field]=value
        assert not check_execution(order,latest)['complete']


def test_fill_price_identity_ownership_duplicates_and_dates_must_match():
    import copy
    for field,value in [('price_usd','200'),('quantity','0.6'),('symbol','MSFT'),('side','sell'),
                        ('executor','legacy_manual'),('effective_at','2026-09-08T13:47:00Z'),('fee_usd','NaN')]:
        order,latest=execution_ledger_case();latest['report']['fills'][0][field]=value
        assert not check_execution(order,latest)['complete'],field
    order,latest=execution_ledger_case()
    latest['report']['fills'].append(copy.deepcopy(latest['report']['fills'][0]))
    assert check_execution(order,latest)['orders'][0]['issues']==['duplicate_fill_source_ids']


def test_split_fills_use_weighted_price_and_preserve_unrelated_activity():
    import copy
    order,latest=execution_ledger_case()
    first=latest['report']['fills'][0];first.update(quantity='0.2',price_usd='199.2')
    second=copy.deepcopy(first);second.update(source_id='fill2',quantity='0.3',price_usd='199.7')
    unrelated=copy.deepcopy(first);unrelated.update(source_id='outside',broker_order_id='outside',quantity='99',executor='legacy_manual')
    latest['report']['fills'].extend([second,unrelated])
    assert check_execution(order,latest)['complete']
    order['broker_receipt']['observation']['average_fill_price_usd']='199.50009'
    assert check_execution(order,latest)['complete']
    order['broker_receipt']['observation']['average_fill_price_usd']='199.50011'
    assert not check_execution(order,latest)['complete']


def test_no_fill_cancellation_and_local_only_dispositions_are_distinguished():
    order,latest=execution_ledger_case()
    order['broker_receipt']['filled_quantity']='0'
    order['broker_receipt']['observation'].update(filled_quantity='0',average_fill_price_usd=None)
    latest['report']['fills']=[]
    assert check_execution(order,latest)['complete']
    order['broker_receipt']=None
    result=check_execution(order,latest)
    assert not result['complete'] and result['orders'][0]['state']=='local_only'


def test_future_closing_observation_cannot_complete_elapsed_session():
    sessions=[{'session_date':'2026-09-08','opens_at':'2026-09-08T13:30:00Z','closes_at':'2026-09-08T20:00:00Z'}]
    rows=[{'reconciliation_id':at,'observed_at':at,
           'report':{'reconciled':True,'evidence_kind':'broker_paper'}}
          for at in ['2026-09-08T13:31:00Z','2026-09-08T20:01:00Z']]
    now=datetime(2026,9,8,20,0,30,tzinfo=timezone.utc)
    assert report.session_evidence(sessions,rows,now)[0]['state']=='missing_observations'


def test_research_readiness_uses_verified_sources_and_matching_frozen_criteria(monkeypatch,tmp_path):
    from scripts.research import review_paper_trial_data as source
    review={'criteria_hash':'criteria','readiness':'source_capture_complete_research_admission_incomplete',
        'reviewed_at':'2026-09-07T00:00:00Z','calendar_sessions':2,
        'feeds':{'sip':{'source_rows':8}},'historical_windows':{},
        'corporate_actions':{'dividends_missing_currency':1},
        'action_effective_window_review':{'missing_from_original':[{'source_id':'event'}]},
        'remaining':['Historical availability unverified.']}
    def verified(root):
        assert root==tmp_path
        return review
    monkeypatch.setattr(source,'build_review',verified)
    result=report.research_readiness(tmp_path/'trial-plan.json',{'criteria_hash':'criteria'})
    assert result['bars_per_feed']=={'sip':8}
    assert result['remaining']==review['remaining'] and result['review_hash']
    assert result['known_effective_window_omissions']==1
    mismatch=report.research_readiness(tmp_path/'trial-plan.json',{'criteria_hash':'different'})
    assert mismatch['state']=='unavailable' and 'bars_per_feed' not in mismatch


def test_missing_or_corrupt_source_evidence_does_not_infer_readiness(monkeypatch,tmp_path):
    from scripts.research import review_paper_trial_data as source
    for error in [FileNotFoundError('missing'),ValueError('hash mismatch'),AssertionError('incomplete')]:
        def broken(root):
            raise error
        monkeypatch.setattr(source,'build_review',broken)
        result=report.research_readiness(tmp_path/'trial-plan.json',{'criteria_hash':'criteria'})
        assert result['state']=='unavailable' and result['remaining']
        assert 'review_hash' not in result
