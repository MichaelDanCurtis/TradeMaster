"""Declare a bounded follow-up experiment before computing new results."""
import argparse,json,hashlib
from pathlib import Path
from datetime import datetime,timezone

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True);ap.add_argument('--root',type=Path,required=True);a=ap.parse_args();a.root.mkdir(exist_ok=False,parents=True)
 for d in ['sec','prices','historical','code']:(a.root/d).mkdir()
 protocol={'declared_at':datetime.now(timezone.utc).isoformat(),'source':str(a.source.resolve()),'source_hashes':{str(p.relative_to(a.source)):sha(p) for p in [a.source/'universe.json',a.source/'universe-source/universe.json',a.source/'panel-diverse100-quality.json',a.source/'panel-sp500-quality.json']},
 'evaluation':'2021-09-07 open through 2026-09-04 open; 60 original origins; previously observed interval, follow-up exploratory comparison, not untouched holdout',
 'universes':['same diverse100 cohort','same current S&P roster','historical S&P reconstruction, conditional on complete security/terminal-price coverage'],
 'variants':['hgb','hgb_buffer','hgb_buffer_risk','hgb_fundamentals','hgb_fundamentals_buffer_risk','SPY'],
 'hgb':'Same original 100 iterations, learning_rate .03, max_depth2, max_leaf_nodes4, min_samples_leaf50, l2=1, early_stopping false, seed59137; expanding only matured training labels; no tuning',
 'buffer':{'selected_fraction':'ceil(eligible/3)','retention_rank_fraction':.45,'challenger_score_advantage':.005,'rule':'Retain eligible incumbents while rank <=ceil(.45*N); replace weakest with best outsider only if score advantage >=.005. Fill/prune to fixed target count; equal weight before risk layer.'},
 'risk':{'lookback_sessions':63,'weights':'inverse historical volatility; cap each security5%, each current sector20%; leave infeasible budget in cash','covariance_shrinkage_to_diagonal':.5,'volatility_target':'past63 SPY annualized volatility; only scale down, never leverage','rebalancing':'monthly target limits; may drift between rebalances; cash earns zero'},
 'fundamentals':{'source':'SEC companyfacts, annual US-GAAP USD and USD/shares observations; filing date strictly before decision date; only 10-K/10-Q and amendments; as-of revisions only; future-filed observations excluded','metrics':['net_income/assets','operating_cash_flow/assets','free_cash_flow/assets','revenue_growth','operating_cash_flow_growth','liabilities/assets','cash/assets','annual_diluted_earnings_yield'],'maximum_period_end_age_days':550,'annual_duration_days':[330,400],'growth_period_end_separation_days':[330,400],'matching_periods':'ratio components must share financial period end; duration components must share start and end','valuation':'annual diluted EPS / raw close, omitted for multiple listed share classes and when split factor changes between EPS period end and decision; split and raw bars captured separately','missing':'NaN preserved for native HGB handling; within-origin observed-value percentile ranks; no future filling or universe drops for missing fundamentals','limits':'current aggregate SEC history with filed-date filtering, not guaranteed complete archival vintage; liabilities/assets is broad leverage proxy, not interest-bearing debt ratio'},
 'cost_bps_per_side':[11,22],'holdout_policy':'No already inspected dates are called unseen. Historical membership is a new universe robustness check, not a pristine holdout. A prospectively frozen candidate can be tested on future data only after qualification; no new automatic trades authorized here.',
 'historical_policy':'Use reported dated membership; query former tickers with asof date during membership. Preserve missing symbols/prices. No stale-price liquidation, zero writeoffs or invented merger consideration. Full performance unqualified if identities or delisted terminal events unresolved.',
 'decision_rule':'Report every variant, net CAGR, drawdown, volatility, turnover, fees, concentration and paired period excess. No retries/tuning based on outcomes. Improvements require honest risk/cost comparison; no promotion from this exploratory run.'}
 (a.root/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n');print(a.root)
if __name__=='__main__':main()
