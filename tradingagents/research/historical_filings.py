"""Historical filing support; identity and portfolio rules never inspect prices."""
from datetime import date
import math
from lxml import etree
from tradingagents.research.filing_identity import FIELDS, local, normalize_date, scoped_identity


def instance_identity(raw, record):
    """Validate a separate, same-accession XBRL instance's non-dimensional DEI."""
    root = etree.fromstring(raw, parser=etree.XMLParser(resolve_entities=False, no_network=True))
    if local(root.tag) != 'xbrl':
        raise ValueError('Not an XBRL instance')
    contexts = set()
    for n in root.iter():
        if local(n.tag) != 'context':
            continue
        nodes = list(n.iter())
        ids = [(x.text or '').strip() for x in nodes if local(x.tag) == 'identifier']
        ends = [(x.text or '').strip() for x in nodes if local(x.tag) in {'enddate', 'instant'}]
        dimensional = any(local(x.tag) in {'segment', 'scenario', 'explicitmember', 'typedmember'} for x in nodes)
        if (len(ids) == 1 and ids[0].isdigit() and int(ids[0]) == int(record['cik'])
                and ends == [record['reportDate']] and not dimensional):
            if n.get('id') in contexts:
                raise ValueError('Duplicate eligible context')
            contexts.add(n.get('id'))
    values, evidence = {}, []
    for n in root.iter():
        key = local(n.tag)
        namespace = etree.QName(n).namespace if isinstance(n.tag, str) else None
        if (key not in FIELDS or n.get('contextRef') not in contexts
                or not namespace or not namespace.startswith(('http://xbrl.sec.gov/dei/', 'https://xbrl.sec.gov/dei/'))):
            continue
        value = ' '.join(' '.join(n.itertext()).split())
        if key == 'documentperiodenddate':
            value = normalize_date(value, '')
        values.setdefault(key, set()).add(value)
        evidence.append({'field': key, 'context_id': n.get('contextRef'), 'value': value})
    return {'dei': {k: sorted(v) for k, v in values.items()}, 'evidence': evidence,
            'eligible_contexts': sorted(contexts), 'method': 'same_accession_external_xbrl_v1'}


def choose_portfolio(members, issuer_map, pairs, decision, freshness=180):
    """Latest structurally valid, available pair per issuer; one security per issuer.

    Unknown identities remain in the coverage ledger. Ties are deterministic.
    Members must be the previous session's dated universe. No price input exists.
    """
    available = {}
    for p in pairs:
        if p['status'] != 'structurally_validated' or not p.get('eligible_entry_date'):
            continue
        age = (date.fromisoformat(decision) - date.fromisoformat(p['new']['filingDate'])).days
        if p['eligible_entry_date'] > decision or not 0 <= age <= freshness:
            continue
        cik = p['new']['cik']
        key = (p['new']['filingDate'], p['new']['acceptanceDateTime'], p['new']['accessionNumber'])
        if cik not in available or key > available[cik][0]:
            available[cik] = (key, p)
    ledger, eligible, seen = [], [], set()
    for s in sorted(members):
        cik = issuer_map.get(s, '')
        state = 'eligible'
        if not str(cik).isdigit(): state = 'unmapped_historical_issuer'
        elif cik in seen: state = 'duplicate_issuer_share_class'
        elif cik not in available: state = 'no_qualified_fresh_pair'
        else:
            seen.add(cik)
            p = available[cik][1]
            eligible.append({'symbol': s, 'cik': cik, 'score': p['jaccard'],
                             'accession': p['new']['accessionNumber'], 'eligible_entry_date': p['eligible_entry_date']})
        ledger.append({'symbol': s, 'cik': cik, 'state': state})
    ranked = sorted(eligible, key=lambda x: (-x['score'], x['cik'], x['symbol']))
    count = math.ceil(len(ranked) / 3)
    return {'date': decision, 'eligible': ranked, 'selected': [x['symbol'] for x in ranked[:count]],
            'coverage': ledger, 'member_count': len(members)}


def historical_inline_identity(raw, record):
    # Old SEC HTML commonly contains comment nodes. The frozen modern parser
    # assumes element attributes, so remove comments from the identity view only.
    # Original bytes and narrative normalization are unchanged.
    tree = etree.HTML(raw, parser=etree.HTMLParser(no_network=True, remove_comments=True, remove_pis=True))
    if tree is None:
        raise ValueError('No HTML document')
    return scoped_identity(etree.tostring(tree), record)
