"""Bounded public-company lookup. No account credentials or model calls."""
import json
import sys
import warnings


def main(symbol):
    import yfinance as yf
    warnings.simplefilter('ignore')
    ticker = yf.Ticker(symbol)
    fields = ['symbol', 'longName', 'shortName', 'quoteType', 'sector', 'industry', 'country', 'website',
              'longBusinessSummary', 'parentCompany', 'fundFamily', 'marketCap', 'enterpriseValue', 'trailingPE',
              'forwardPE', 'trailingEps', 'totalRevenue', 'profitMargins', 'revenueGrowth', 'freeCashflow',
              'totalCash', 'totalDebt', 'fullTimeEmployees', 'heldPercentInsiders', 'heldPercentInstitutions', 'currency']
    info = ticker.get_info()
    result = {'info': {k: info.get(k) for k in fields}, 'institutional': [], 'insiders': [], 'gaps': []}
    for key, method in [('institutional', ticker.get_institutional_holders), ('insiders', ticker.get_insider_roster_holders)]:
        try:
            frame = method()
            if frame is not None:
                result[key] = json.loads(frame.head(50).to_json(orient='records', date_format='iso'))
        except Exception:
            result['gaps'].append(key + ' holder records unavailable.')
    print(json.dumps(result, allow_nan=False))


if __name__ == '__main__':
    main(sys.argv[1])
