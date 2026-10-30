"""Audit a free historical institutional-holdings archive; no returns or signals."""
import argparse,csv,io,json,zipfile
from collections import Counter,defaultdict
from datetime import datetime
from pathlib import Path
from scripts.research.event_research_pilot import Capture,digest,now,read,write_new

URL='https://www.sec.gov/files/structureddata/data/form-13f-data-sets/2019q2_form13f.zip'
README='https://www.sec.gov/files/form_13f_readme.pdf'


def date(s):return datetime.strptime(s,'%d-%b-%Y').date().isoformat()


def run(root):
    if not root.exists():
        root.mkdir(parents=True);(root/'raw').mkdir()
        write_new(root/'protocol.json',{'created_at':now(),'scope':'Historical ownership data engineering only; no return labels, reinvestment or predictive claims',
          'archive_url':URL,'source_documentation':README,'period':'2019Q2 filings','asof':'2019-06-30',
          'example':'Red Hat common-share ownership in unamended original March 31 reports; all other rows retained in aggregate audit',
          'amendments':'Flag and exclude affected managers from the unamended original subset; do not merge amendments naively',
          'value_units':'2019 filing values are in thousands of USD per SEC data dictionary; number of shares is separate',
          'budget_new_data_subscriptions_usd':0,'code_sha256':digest(Path(__file__))})
    p=read(root/'protocol.json')
    if digest(Path(__file__))!=p['code_sha256']:raise ValueError('Audit code changed')
    config={'headers':{'User-Agent':'TradeMasterResearch/1.0 personal desktop research'},'minimum_request_spacing_seconds':1,'max_attempts':3,'workers':1}
    c=Capture(root,config)
    try:
        raw=c.get(URL);c.get(README)
    finally:c.close()
    if raw is None:raise ValueError('Public archive unavailable')
    archive=zipfile.ZipFile(io.BytesIO(raw))
    if len(archive.infolist())>30 or sum(i.file_size for i in archive.infolist())>8*1024**3:raise ValueError('Unexpected archive size')
    names={Path(n).name.upper():n for n in archive.namelist()}
    def rows(name):
        return csv.DictReader(io.TextIOWrapper(archive.open(names[name]),encoding='utf-8-sig'),delimiter='\t')
    submissions={r['ACCESSION_NUMBER']:r for r in rows('SUBMISSION.tsv'.upper())}
    report_type=Counter(r['SUBMISSIONTYPE'] for r in submissions.values())
    original=defaultdict(list);amended=set()
    for accession,s in submissions.items():
        if date(s['FILING_DATE'])>p['asof'] or date(s['PERIODOFREPORT'])!='2019-03-31':continue
        if s['SUBMISSIONTYPE']=='13F-HR':original[s['CIK']].append(accession)
        elif s['SUBMISSIONTYPE']=='13F-HR/A':amended.add(s['CIK'])
    eligible={a[0] for cik,a in original.items() if len(a)==1 and cik not in amended}
    count=0;orphans=0;types=Counter();examples=[];eligible_rows=0
    for r in rows('INFOTABLE.tsv'.upper()):
        count+=1;acc=r['ACCESSION_NUMBER'];types[(r['SSHPRNAMTTYPE'],r['PUTCALL'])]+=1
        if acc not in submissions:orphans+=1
        if acc in eligible:
            eligible_rows+=1
            if 'RED HAT' in r['NAMEOFISSUER'].upper() and r['SSHPRNAMTTYPE']=='SH' and not r['PUTCALL']:
                s=submissions[acc]
                examples.append({'accession':acc,'manager_cik':s['CIK'],'filed':date(s['FILING_DATE']),
                    'reported':date(s['PERIODOFREPORT']),'issuer':r['NAMEOFISSUER'],'class':r['TITLEOFCLASS'],
                    'cusip':r['CUSIP'],'reported_shares':r['SSHPRNAMT'],'raw_value_thousands_usd':r['VALUE'],
                    'shared_discretion_manager':r['OTHERMANAGER'],'investment_discretion':r['INVESTMENTDISCRETION']})
    result={'created_at':now(),'archive_sha256':read(root/'receipt.json')[__import__('hashlib').sha256(URL.encode()).hexdigest()]['sha256'],
       'archive_bytes':len(raw),'files':{i.filename:i.file_size for i in archive.infolist()},
       'submissions':len(submissions),'submission_types':dict(report_type),'raw_position_rows':count,
       'orphan_position_accessions':orphans,'share_principal_option_types':{str(k):v for k,v in types.items()},
       'unamended_original_march31_managers':len(eligible),'unamended_original_rows':eligible_rows,
       'march31_managers_with_amendments_in_archive':len(amended),'red_hat_candidate_rows':len(examples),
       'red_hat_distinct_managers':len({x['manager_cik'] for x in examples}),
       'red_hat_examples':examples,
       'limitations':['Manager-level reporting is not a complete fund-by-fund ownership graph',
                      'One filing quarter does not guarantee complete amendment history or confidential holdings',
                      'Duplicate/shared discretion rows need economic aggregation before use',
                      'Names and CUSIPs need historical security qualification',
                      'Current bulk files were reprocessed; original filings need cross-checks',
                      'Public holdings do not establish actual cash receipts, reinvestment or predictive power']}
    write_new(root/'audit.json',result)
    write_new(root/'manifest.json',{str(x.relative_to(root)):digest(x) for x in root.rglob('*') if x.is_file()})
    print(json.dumps({k:v for k,v in result.items() if k not in ['red_hat_examples','files','share_principal_option_types']}),flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
