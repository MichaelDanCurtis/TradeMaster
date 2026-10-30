"""Read-only verification and report for a frozen historical filing experiment."""
import argparse
from collections import Counter
from pathlib import Path
import math
from scripts.research.event_research_pilot import digest, read, write_new, now
from scripts.research.historical_filing_study import check, check_pairs
from tradingagents.research.filing_stability import conservative_public_time
from datetime import timedelta


def verify(root):
    p=check(root);check_pairs(root)
    receipt=read(root/'receipt.json'); checked=0
    for r in receipt.values():
        if r.get('sha256'):
            if digest(root/r['file'])!=r['sha256']:raise ValueError('Raw source changed')
            checked+=1
    signals=read(root/'signals.json')
    if digest(root/'signals.json')!=read(root/'signals-lock.json')['sha256']:raise ValueError('Signals changed')
    for f,h in read(root/'signals-lock.json')['document_hashes'].items():
        if digest(root/f)!=h:raise ValueError('Document changed')
    valid={}
    for pair in signals['pairs']:
        if pair['status']!='structurally_validated':continue
        docs=[read(root/'normalized'/(r['cik']+'_'+r['accessionNumber']+'.json')) for r in [pair['new'],pair['old']]]
        a,b=[set(d['tokens']) for d in docs]
        if pair['jaccard']!=len(a.intersection(b))/len(a.union(b)):raise ValueError('Jaccard mismatch')
        valid[(pair['new']['cik'],pair['new']['accessionNumber'])]=pair
    targets=read(root/'targets.json')
    if digest(root/'targets.json')!=read(root/'targets-lock.json')['sha256']:raise ValueError('Targets changed')
    u=read(root/'universe.json');cal=read(Path(p['calendar']))
    for decision,universe in zip(targets['decisions'],u['decisions']):
        ranked=decision['eligible'];seen=set()
        for x in ranked:
            if x['symbol'] not in universe['members'] or x['symbol'] in universe.get('identity_conflicts',[]) or x['cik'] in seen:raise ValueError('Invalid member/duplicate issuer')
            seen.add(x['cik']);pair=valid[(x['cik'],x['accession'])]
            # Independent date-based bound: all historical availability is after NY midnight.
            # Existing unit tests also exercise precise open/close and holiday arithmetic.
            known=conservative_public_time(pair['new'])+timedelta(seconds=300)
            from datetime import datetime
            from zoneinfo import ZoneInfo
            after=[r['date'] for r in cal if datetime.fromisoformat(r['date']+'T'+r['open']).replace(tzinfo=ZoneInfo('America/New_York'))>known]
            if after[2]!=pair['eligible_entry_date'] or after[2]>decision['date']:raise ValueError('Availability violation')
        expected=sorted(ranked,key=lambda x:(-x['score'],x['cik'],x['symbol']))[:math.ceil(len(ranked)/3)]
        if decision['selected']!=[x['symbol'] for x in expected]:raise ValueError('Ranking mismatch')
    return {'verified_at':now(),'raw_sources_hashed':checked,'signals_recomputed':len(valid),
            'decision_timing_and_ranking':'passed','scope':'Independent arithmetic and availability checks; shared original-document parser, not independent semantic audit'}


def report(root):
    verification=verify(root);write_new(root/'verification.json',verification)
    targets=read(root/'targets.json');signals=read(root/'signals.json');results=read(root/'results.json')['results']
    lines=['# Historical filing stability: public-data first test','',
       '**Scope:** F1-SP500-EW-v1, April 1, 2019–September 3, 2021. New data subscriptions: $0.',
       'Original filings; ten quarterly decisions; top-third stability, equal weighted; delayed executable entries. The interval is previously examined and shorter than three years.','',
       '## Results','', '| Portfolio | Cost per side | State | CAGR | Maximum drawdown | Daily valuation gaps |',
       '|---|---:|---|---:|---:|---:|']
    for name,costs in results.items():
        for cost,r in costs.items():
            value=lambda k:f"{r[k]:.2%}" if k in r else 'Unavailable'
            lines.append(f"| {name} | {cost} bps | {r['state']} | {value('cagr')} | {value('max_drawdown')} | {len(r.get('valuation_gaps',[]))} |")
    lines+=['','An incomplete portfolio has no full-period return. With missing daily marks, reported drawdown can understate the true loss. No missing holdings are silently removed.','',
        '## Coverage','',f"Candidate filing pairs: {len(signals['pairs'])}; structural status: {signals['counts']}.",'',
        '| Decision | Historical members | Filing-eligible issuers | Selected | Unmapped or date-conflicting identities |',
        '|---|---:|---:|---:|---:|']
    for d in targets['decisions']:
        counts=Counter(x['state'] for x in d['coverage'])
        lines.append(f"| {d['date']} | {d['member_count']} | {len(d['eligible'])} | {len(d['selected'])} | {counts['unmapped_historical_issuer']} |")
    reasons=Counter(reason for x in signals['pairs'] for reason in x['issues'])
    lines+=['','Pair rejection reasons: '+str(dict(reasons))+'.','',
       '## Interpretation limits','',
       '- Historical membership comes from a pinned community reconstruction. The supplemental public issuer archive fills inherited missing CIKs but can contain later field corrections. Conflicting dated identities are excluded. Missing filings and security-lineage errors can still produce coverage selection; the matched eligible control does not eliminate every such bias.',
       '- The matched equal-weight control isolates selection within the available filing cohort. SPY is the whole-account reference. The full-membership control exposes unaccounted securities; it is not replaced with survivors.',
       '- Existing event accounting credits economic merger entitlements and permits fractional successor shares. It is not settlement accounting or proof of complete corporate-action coverage.',
       '- Fixed cost assumptions are 11 and 22 basis points per side; taxes, market impact and actual execution are not established.',
       '- These results cannot establish the roadmap’s rolling 36-month objective or a robust SPY-beating strategy. A positive result is a candidate for further qualification, not investment approval.','',
       '## Verification','',str(verification),'',
       'The evaluator also replayed each portfolio using independently implemented rebalance arithmetic. Event sequencing is shared, so this is not a fully independent backtest engine.','',
       '## Reproduction','', 'Run stages with `PYTHONPATH=. .venv/bin/python scripts/research/historical_filing_study.py STAGE --root NEW_ROOT`: `freeze`, `metadata`, `plans`, `capture`, `normalize`, `targets`. Use `.venv-prediction-lab/bin/python` for `score`, then this report script. Artifacts are write-once.','']
    (root/'report.md').write_text('\n'.join(lines))
    write_new(root/'report-manifest.json',{'report.md':digest(root/'report.md'),'verification.json':digest(root/'verification.json'),
                                         'report_script_sha256':digest(Path(__file__))})
    print(verification)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True)
    report(ap.parse_args().root)
