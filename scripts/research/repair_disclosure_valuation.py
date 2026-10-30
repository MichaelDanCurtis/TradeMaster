"""Explicit DOW valuation sensitivity, preserving every frozen selection."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from scripts.research.disclosure_signals import sha, write


def prepare(root):
    target = root/'dow-valuation'
    target.mkdir(exist_ok=False)
    archive = Path('.research-artifacts/prediction-wide-2026-09-07/capture-audit-dow')
    receipt = json.loads((archive/'receipt.json').read_text())
    for row in receipt:
        if sha(archive/row['file']) != row['sha256']:
            raise ValueError('Archived provider response changed')
    if receipt[0]['sha256'] != receipt[1]['sha256']:
        raise ValueError('Independent asof requests disagree')
    panel = json.loads((root/'panel.json').read_text())
    original = sha(root/'panel.json')
    positions = {d: i for i, d in enumerate(panel['dates'])}
    bars = json.loads((archive/'response-0.json').read_text())['bars']['DOW']
    filled = []
    for bar in bars:
        d = bar['t'][:10]
        if d < '2019-04-02' or d not in positions or bar['v'] <= 0:
            continue
        i = positions[d]
        if panel['series']['DOW']['open'][i] is not None:
            raise ValueError('Would overwrite an existing observed price')
        for field, key in [('open', 'o'), ('high', 'h'), ('low', 'l'), ('close', 'c'), ('volume', 'v'), ('vwap', 'vw')]:
            panel['series']['DOW'][field][i] = bar[key] if bar[key] > 0 else None
        filled.append(d)
    write(target/'panel.json', panel)
    inputs = {str(root/'targets-lock.json'): sha(root/'targets-lock.json'), str(root/'panel.json'): original,
              str(archive/'response-0.json'): sha(archive/'response-0.json'), str(archive/'response-1.json'): sha(archive/'response-1.json'),
              str(archive/'issuer-separation.html'): sha(archive/'issuer-separation.html'), str(Path(__file__)): sha(__file__)}
    write(target/'protocol.json', {'declared_at': datetime.now(timezone.utc).isoformat(), 'inputs': inputs,
          'panel_sha256': sha(target/'panel.json'), 'filled': len(filled), 'first': min(filled), 'last': max(filled),
          'reason': 'Original source has no DOW. Two archived alternate-asof responses agree. Restrict to post-separation regular-way common shares from2019-04-02. No pre-inception history or ticker substitution.',
          'issuer_source': 'https://investors.dow.com/en/news/news-details/2019/Dow-completes-separation-from-DowDuPont/default.aspx',
          'qualification': 'Explicit alternate-asof price-source sensitivity. Provider mapping cause unresolved; not fully admitted data. No selections or other prices changed.'})
    print('Prepared', target, len(filled), 'observed post-inception DOW sessions')


def score(root):
    from scripts.research.prediction_event_accounting import simulate_events
    from scripts.research.evaluate_astra_capsules import compare_recursive
    target = root/'dow-valuation'; amendment = json.loads((target/'protocol.json').read_text())
    if any(sha(p) != h for p, h in amendment['inputs'].items()) or sha(target/'panel.json') != amendment['panel_sha256']:
        raise ValueError('Frozen valuation sensitivity changed')
    lock = json.loads((root/'targets-lock.json').read_text())
    if any(sha(root/name) != h for name, h in lock['files'].items()):
        raise ValueError('Original selections or inputs changed')
    protocol = json.loads((root/'protocol.json').read_text()); panel = json.loads((target/'panel.json').read_text())
    result = {}; replay_count = 0
    for experiment in protocol['experiments']:
        label = experiment['label']; result[label] = {}
        for delay in protocol['additional_session_delays']:
            rows = json.loads((root/f'{label}-delay{delay}-targets.json').read_text())
            for bps in protocol['cost_bps']:
                a = simulate_events(panel, rows, panel['valuation_only_reconciliation']['events'], bps/10000)
                b = simulate_events(panel, rows, panel['valuation_only_reconciliation']['events'], bps/10000, audit=True)
                compare_recursive(a, b); replay_count += 1
                result[label][f'delay{delay}-cost{bps}'] = a
                print(label, delay, bps, a['state'], a.get('cagr'), a.get('date'), a.get('unresolved_symbols'), flush=True)
        original = json.loads((root/'results.json').read_text())[label]
        for bps in protocol['cost_bps']:
            result[label][f'SPY-cost{bps}'] = original[f'SPY-cost{bps}']
        write(target/'results.json', result)
    write(target/'verification.json', {'two_cost_solver_replays': replay_count, 'original_target_hashes_verified': True,
                                       'note': 'SPY controls unchanged from original replay; shared corporate-action engine.'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['prepare', 'score']); parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    (prepare if args.stage == 'prepare' else score)(args.root)
