"""Refresh AI/biomed patent families, with strict export and classification checks."""
import argparse, collections, csv, json, math
from datetime import datetime
from pathlib import Path
from common import ROOT,read_csv,write_csv,save_json,digest,now
from patent_base import classify

OUT=ROOT/'results/patents'
SQL=ROOT/'sql/ai_biomed_2015_2025.sql'

def validate_export(path):
    rows=read_csv(path)
    manifests=[r for r in rows if r.get('row_type')=='manifest']
    data=[r for r in rows if r.get('row_type')=='data']
    if len(manifests)!=1 or len(rows)!=len(data)+1:
        raise ValueError('Use the bundled SQL and export ALL rows, including exactly one manifest row.')
    expected=int(manifests[0]['export_total_rows'])
    if len(data)!=expected or any(int(r['export_total_rows'])!=expected for r in data):
        raise ValueError('Truncated export: expected %d, received %d family rows.'%(expected,len(data)))
    seen=set()
    for r in data:
        if r['industry'] not in ('ai','biomed') or r['city'] not in ('hk','sg'):
            raise ValueError('Unexpected industry/city')
        dt=datetime.strptime(r['first_filing_in_window'],'%Y%m%d')
        if not 2015<=dt.year<=2025 or r['quarter']!=f'{dt.year}Q{(dt.month-1)//3+1}':
            raise ValueError('Invalid filing year/quarter')
        key=(r['industry'],r['city'],r['family_id'])
        if key in seen: raise ValueError('Duplicate industry/city/family: '+str(key))
        seen.add(key)
    return data,manifests[0]

def maps():
    smap={r['assignee']:r['sector'] for r in read_csv(ROOT/'config/assignee_sectors.csv')}
    extra=ROOT/'config/new_assignees.csv'
    if extra.exists():
        for r in read_csv(extra):
            s=r['sector'].strip()
            if s:
                if s not in ('company','university','public_rd','individual','legacy_noncompany'): raise ValueError('Invalid sector: '+s)
                smap[r['assignee'].strip()]=s
    excluded={(r['city'],r['assignee']) for r in read_csv(ROOT/'config/exclusions.csv') if r['exclude_level'] in ('ali_grp','ant_grp')}
    return smap,excluded

def compute(rows,smap,excluded):
    audit=[];unknown=collections.Counter();counts=collections.Counter();pending=collections.Counter()
    invalid=[]
    for industry in ('ai','biomed'):
        selected=[]
        for r in rows:
            if r['industry']!=industry:continue
            if r['family_id'] in ('','0','-1','None','null') or not r['assignees'].strip():
                invalid.append(r);continue
            selected.append(r)
        c,p,u,a=classify(selected,smap,excluded)
        for k,n in c.items():counts[(industry,*k)]+=n
        for k,n in p.items():pending[(industry,*k)]+=n
        unknown.update(u)
        for item in a:
            audit.append(dict(zip(['industry','city','quarter','family_id','assignees','status','unclassified_names','group_alias_to_review'],[industry]+item)))
    return audit,unknown,counts,pending,invalid

def aggregate(path,out=OUT):
    rows,meta=validate_export(path);smap,excluded=maps()
    audit,unknown,counts,pending,invalid=compute(rows,smap,excluded)
    annual=[];quarterly=[]
    for i in ('ai','biomed'):
      for c in ('hk','sg'):
       for y in range(2015,2026):
        n=p=0
        bad=sum(r['industry']==i and r['city']==c and r['quarter'].startswith(str(y)) for r in invalid)
        for q in range(1,5):
            key=(i,c,f'{y}Q{q}');n+=counts[key];p+=pending[key]
            quarterly.append(dict(industry=i,city=c,quarter=key[2],confirmed_families=counts[key],pending_families=pending[key]))
        annual.append(dict(year=y,industry=i,city=c,confirmed_families=n,pending_families=p,invalid_rows=bad,
             usable_observed_count=n if not p and not bad else '',published_snapshot_only=1,
             status='needs_classification' if p or bad else 'observed_not_final' if y>=2024 else 'observed_historical'))
    write_csv(out/'年度专利.csv',annual,list(annual[0]))
    write_csv(out/'季度专利.csv',quarterly,list(quarterly[0]))
    write_csv(out/'family_audit.csv',audit,['industry','city','quarter','family_id','assignees','status','unclassified_names','group_alias_to_review'])
    write_csv(out/'new_assignees_to_classify.csv',[dict(city=c,assignee=a,sector='',family_industry_occurrences=n) for (c,a),n in sorted(unknown.items())],['city','assignee','sector','family_industry_occurrences'])
    write_csv(out/'invalid_rows.csv',invalid,['industry','city','quarter','family_id','first_filing_in_window','assignees'])
    baseline=[]
    for f in sorted((ROOT/'baseline/patents').glob('*.csv')):
        if f.name.endswith('_audit.csv'):continue
        baseline+=read_csv(f)
    ba,_,_,_,_=compute(baseline,smap,excluded)
    old={(r['industry'],r['city'],r['family_id']):r for r in ba}
    new={(r['industry'],r['city'],r['family_id']):r for r in audit}
    changes=[]
    for k in sorted(old.keys()|new.keys()):
        a=old.get(k,{});b=new.get(k,{})
        if (a.get('quarter'),a.get('status'))!=(b.get('quarter'),b.get('status')):
            changes.append(dict(industry=k[0],city=k[1],family_id=k[2],old_quarter=a.get('quarter',''),new_quarter=b.get('quarter',''),old_status=a.get('status',''),new_status=b.get('status','')))
    write_csv(out/'与旧快照差异.csv',changes,['industry','city','family_id','old_quarter','new_quarter','old_status','new_status'])
    # Preserve new export; do not splice current families into old counts.
    raw=out/'raw_export.csv'
    if Path(path).resolve()!=raw.resolve():raw.write_bytes(Path(path).read_bytes())
    report=dict(collected_utc=now(),rows=len(rows),export_verified=True,sql_sha256=digest(SQL),raw_sha256=digest(raw),
        classification_pending=sum(pending.values()),invalid_rows=len(invalid),max_publication_date=meta['max_pub_in_query'],
        filing_window='2015-2025',geography='harmonized assignee country HK/SG',family_complete=False,
        config_sha256={p.name:digest(p) for p in sorted((ROOT/'config').glob('*.csv'))},
        note='Published observations only. No unpublished-patent extrapolation; 2024/2025 remain provisional.')
    save_json(out/'manifest.json',report)
    print('Patent results:',out,'; pending:',report['classification_pending'],'; invalid:',len(invalid),flush=True)
    return report

def cloud(project,execute,max_gb,out=OUT):
    from google.cloud import bigquery
    if not math.isfinite(max_gb) or max_gb<=0:raise ValueError('--max-gb must be positive and finite')
    client=bigquery.Client(project=project,location='US');sql=SQL.read_text(encoding='utf-8')
    dry=client.query(sql,job_config=bigquery.QueryJobConfig(dry_run=True,use_query_cache=False))
    print('Estimated scanned GB:',round(dry.total_bytes_processed/1e9,3),flush=True)
    if not execute:return
    if dry.total_bytes_processed>max_gb*1e9:raise ValueError('Estimate exceeds cap; no billable job submitted')
    out.mkdir(parents=True,exist_ok=True);jobfile=out/'query_job.json'
    # Reattach unfinished compatible job instead of billing another query after interruption.
    previous=json.loads(jobfile.read_text()) if jobfile.exists() else {}
    if previous.get('project')==project and previous.get('sql_sha256')==digest(SQL) and previous.get('downloaded') is False:
        job=client.get_job(previous['job_id'],location='US')
        if job.error_result:raise RuntimeError('Previous BigQuery job failed. Inspect query_job.json; move it aside before retrying.')
    else:
        job=client.query(sql,job_config=bigquery.QueryJobConfig(maximum_bytes_billed=int(max_gb*1e9)))
        save_json(jobfile,dict(job_id=job.job_id,project=project,sql_sha256=digest(SQL),downloaded=False))
    print('BigQuery job:',job.job_id,flush=True);result=job.result()
    raw=out/'raw_export.csv';fields=[f.name for f in result.schema]
    write_csv(raw,(dict(r) for r in result),fields)
    save_json(jobfile,dict(job_id=job.job_id,project=project,sql_sha256=digest(SQL),downloaded=True,
        total_rows=result.total_rows,bytes_processed=job.total_bytes_processed,bytes_billed=job.total_bytes_billed))
    return aggregate(raw,out)

def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group()
    g.add_argument('--csv',type=Path);g.add_argument('--project')
    p.add_argument('--execute',action='store_true');p.add_argument('--max-gb',type=float,default=50)
    a=p.parse_args()
    if a.execute and not a.project:p.error('--execute requires --project')
    if a.csv:aggregate(a.csv)
    elif a.project:cloud(a.project,a.execute,a.max_gb)
    else:print('Run this SQL and export ALL results:',SQL)
if __name__=='__main__':main()
