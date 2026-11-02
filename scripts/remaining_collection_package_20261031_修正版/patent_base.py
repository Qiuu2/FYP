"""2025 HK/SG AI patent families; stdlib CSV processing, optional BigQuery client."""
import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def read(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def write(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f); w.writerow(header); w.writerows(rows)

def classify(rows, smap, excluded):
    counts, pending, unknown, seen, audit = Counter(), Counter(), Counter(), set(), []
    alias = re.compile(r'ALIBABA|ALIPAY|ANTCHAIN|ANTGROUP|ANT (GROUP|FIN)|ADVANCED NOVA|ADVANCED NEW TECH|ADVANTAGEOUS NEW TECH|BANMA|LAZADA|ALIYUN|CAINIAO', re.I)
    for r in rows:
        key = (r['city'], r['family_id'])
        if key in seen: raise ValueError('Duplicate city/family: '+str(key))
        seen.add(key)
        if r['family_id'] in ('','0','-1','None','null'): raise ValueError('Missing family ID; do not count publications as families.')
        names = [a.strip() for a in r['assignees'].split(' | ') if a.strip()]
        if not names: raise ValueError('Missing assignee: '+str(key))
        missing = [a for a in names if a not in smap]
        for a in missing: unknown[(r['city'],a)] += 1
        companies = [a for a in names if smap.get(a)=='company']
        retained = [a for a in companies if (r['city'],a) not in excluded]
        suspect = [a for a in retained if alias.search(a)]
        # An established non-excluded company suffices even with another unknown co-applicant.
        if any(a not in suspect for a in retained): status='included'
        elif missing or suspect: status='pending'
        else: status='excluded'
        if status=='included': counts[(r['city'],r['quarter'])] += 1
        if status=='pending': pending[(r['city'],r['quarter'])] += 1
        audit.append([r['city'],r['quarter'],r['family_id'],r['assignees'],status,' | '.join(missing),' | '.join(suspect)])
    return counts,pending,unknown,audit

def aggregate(src,out):
    rows=read(src)
    required={'industry','city','quarter','family_id','first_filing_in_window','assignees'}
    with Path(src).open(encoding='utf-8-sig',newline='') as f:
        if not required.issubset(csv.DictReader(f).fieldnames or []): raise ValueError('CSV is not the export of ai_patents_2025.sql')
    for r in rows:
        date=datetime.strptime(r['first_filing_in_window'],'%Y%m%d')
        if r['industry']!='ai' or r['city'] not in ('hk','sg') or date.year!=2025 or r['quarter']!=f'2025Q{(date.month-1)//3+1}':
            raise ValueError('Unexpected country/year/quarter: '+str(r))
    smap={r['assignee']:r['sector'] for r in read(ROOT/'config/assignee_sectors.csv')}
    review=ROOT/'config/new_assignees.csv'
    if review.exists():
        for r in read(review):
            if r['sector'].strip():
                if r['sector'] not in ('company','university','public_rd','individual','legacy_noncompany'): raise ValueError('Invalid sector: '+r['sector'])
                smap[r['assignee']]=r['sector']
    excluded={(r['city'],r['assignee']) for r in read(ROOT/'config/exclusions.csv') if r['exclude_level'] in ('ali_grp','ant_grp')}
    counts,pending,unknown,audit=classify(rows,smap,excluded)
    write(out/'family_audit_2025.csv',['city','quarter','family_id','assignees','status','unclassified_names','group_alias_to_review'],audit)
    write(out/'new_assignees_to_classify.csv',['city','assignee','sector','families'],[(c,a,'',n) for (c,a),n in sorted(unknown.items())])
    annual=[];quarterly=[]
    for c,label in [('hk','香港'),('sg','新加坡')]:
        for q in range(1,5):
            k=(c,f'2025Q{q}');n=counts[k];p=pending[k]
            quarterly.append([k[1],label,n,p,n if not p else '', '已公开观察值；尚未完整'])
        n=sum(counts[c,f'2025Q{q}'] for q in range(1,5));p=sum(pending[c,f'2025Q{q}'] for q in range(1,5))
        annual.append([2025,label,n,p,n if not p else '', '已公开观察值；尚未完整'])
    hdr=['年份','地区','已确认企业专利族','待判断专利族','可用于原口径的观察值','数据状态']
    write(out/'港新AI企业专利_2025年度.csv',hdr,annual)
    write(out/'港新AI企业专利_2025季度.csv',['季度']+hdr[1:],quarterly)
    manifest={'created_utc':datetime.now(timezone.utc).isoformat(),'input':str(src),'input_sha256':hashlib.sha256(Path(src).read_bytes()).hexdigest(),'family_rows':len(rows),'application_window_start':2015,'target_year':2025,'historical_variant':'ali_ant_grp','complete':False,'notes':'Observed published families only. Blank final count means unresolved company/group classification. Not a forecast or complete filing-year total.'}
    manifest['config_sha256']={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in (ROOT/'config').glob('*.csv')}
    manifest['sql_sha256']=hashlib.sha256((ROOT/'ai_patents_2025.sql').read_bytes()).hexdigest()
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Saved:',out,'; unclassified applicants:',len(unknown))

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project',help='Your Google Cloud project ID')
    ap.add_argument('--execute',action='store_true',help='Run query after dry run; default only estimates bytes')
    ap.add_argument('--max-gb',type=float,default=50,help='Billed-byte cap, decimal GB; no promise of free use')
    ap.add_argument('--csv',type=Path,help='Process CSV downloaded from BigQuery without cloud credentials')
    ap.add_argument('--out',type=Path,default=ROOT/'results')
    args=ap.parse_args()
    if args.execute and not args.project:ap.error('--execute requires --project')
    if args.csv and args.project:ap.error('Choose --csv OR --project')
    if not math.isfinite(args.max_gb) or args.max_gb<=0:ap.error('--max-gb must be a finite positive number')
    if args.csv:return aggregate(args.csv,args.out)
    if not args.project:
        print('SQL ready:',ROOT/'ai_patents_2025.sql');print('Use --csv export.csv, or --project YOUR_PROJECT [--execute]');return
    from google.cloud import bigquery
    client=bigquery.Client(project=args.project,location='US')
    sql=(ROOT/'ai_patents_2025.sql').read_text(encoding='utf-8')
    dry=client.query(sql,job_config=bigquery.QueryJobConfig(dry_run=True,use_query_cache=False))
    print('Estimated scanned GB:',round(dry.total_bytes_processed/1e9,3))
    if not args.execute:return
    if dry.total_bytes_processed>args.max_gb*1e9:raise SystemExit('Estimate exceeds --max-gb; no query submitted.')
    job=client.query(sql,job_config=bigquery.QueryJobConfig(maximum_bytes_billed=int(args.max_gb*1e9)))
    print('BigQuery job:',job.job_id,flush=True)
    result=job.result();args.out.mkdir(parents=True,exist_ok=True)
    raw=args.out/'patents_raw_2025.csv';tmp=raw.with_suffix('.csv.part')
    write(tmp,[f.name for f in result.schema],(list(r.values()) for r in result));tmp.replace(raw)
    (args.out/'query_job.json').write_text(json.dumps({'job_id':job.job_id,'project':args.project,'bytes_processed':job.total_bytes_processed,'bytes_billed':job.total_bytes_billed,'sql_sha256':hashlib.sha256(sql.encode()).hexdigest()},indent=2),encoding='utf-8')
    aggregate(raw,args.out)

if __name__=='__main__':main()
